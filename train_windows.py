"""Train the PedroAI DQN agent on Windows with a single Trackmania instance.

Windows counterpart of `train_dqn.py` (same model, rewards and schedule) with:
* one game instance driven through Openplanet + AITool on 127.0.0.1:20131,
* the collector running in its own process (experiences and weight snapshots cross as CPU tensors,
  there is no CUDA IPC on Windows); TMLEARN_WORKERS=threads runs it as a thread instead,
* uint8 frames in the replay buffer (16 GB GPUs),
* offline mode by default: agents, training state and logs saved under `runs/<run name>/`.

Run from D:\\TMAI with `PedroAI.bat` / `tmai.bat` (see README.md), or:
    .venv\\Scripts\\python public-tmlearn\\train_windows.py --help
"""
import argparse
import json
import logging
import os
from pathlib import Path
from functools import partial

import torch
import torch.multiprocessing as mp
from fastai.callback.schedule import SchedCos, SchedExp, combine_scheds
from fastcore.foundation import L

from tmenv.gbx import campaigns_maps_uid, official_campaigns
from tmenv.tmenv import DiscreteActionHandler, Tmenv
from tmenv.wrappers import (
    AlignedState,
    EpisodeInfoWrapper,
    RotationEnvWrapper,
    TelemetryState,
    TrajectoryDoneWrapper,
    TrajectoryEnvWrapper,
    TrajectoryState,
    TrajectoryTravelRewardWrapper,
    TrackDistanceRewardWrapper,
    VisualState,
    WheelState,
)
from tmlearn.agent.dqn import (
    DqnAgent,
    EpsilonGreedyExploration,
    NoExploration,
    RankSoftmaxExploration,
)
from tmlearn.collector import (
    ExplorationSwitcherCallback,
    IgnoreLaggyStepCallback,
    IgnoreIdleDemoCallback,
    IgnoreRespawnAndUnfinished,
    IgnoreUnfocusedStepCallback,
    IgnoreUserRestartCallback,
    LagCallback,
    MemoryFullRecoverCallback,
    SessionScheduler,
    TelemetryTimeoutRecoverCallback,
)
from tmlearn.neural import Conv1dFlat, DuelingNet, Flatten, StateCatNet, TimmModel, init_weights
from tmlearn.replay_buffer import PrioritizedReplayBuffer
from tmlearn.training import (
    ExperienceTimeoutCallback,
    LrSchedulerCallback,
    MapScheduler,
    OneMapScheduler,
    Training,
)

TIMESTEP = 0.1
DISCOUNT_FACTOR = 0.95
# Settings that define a run: saved in <run>/run_config.json and reused by --resume unless given again
RUN_CONFIG_KEYS = ["map", "campaigns", "maps_per_campaign", "episodes_per_map", "width", "height", "no_resize",
                   "no_focus_steal", "analog_steer", "reward", "no_fixed_period", "buffer", "burnin", "lr",
                   "launch", "port", "viewer_port"]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--resume", metavar="RUN", help="resume the run saved in <run-dir>/RUN")
    p.add_argument("--map", metavar="UID", help="train on this single map uid instead of the campaign schedule")
    p.add_argument("--campaigns", type=int, default=13, help="official campaigns in the schedule, oldest first (default 13: Summer 2020 to Summer 2023)")
    p.add_argument("--maps-per-campaign", type=int, default=15, help="first N maps of each campaign (default 15: white, green and blue)")
    p.add_argument("--episodes-per-map", type=int, default=10, help="episodes played on a map before switching (default 10)")
    p.add_argument("--run-dir", default="runs", help="where offline runs are saved (default ./runs)")
    p.add_argument("--launch", help="start Trackmania if it is not running: steam, ubisoft or a path to Trackmania.exe")
    p.add_argument("--port", type=int, default=20131, help="AITool plugin socket port (default 20131)")
    p.add_argument("--width", type=int, default=960, help="game window client width (default 960)")
    p.add_argument("--height", type=int, default=540, help="game window client height (default 540)")
    p.add_argument("--no-resize", action="store_true", help="don't resize the Trackmania window")
    p.add_argument("--no-focus-steal", action="store_true", help="never bring Trackmania to the foreground, wait for you to focus it")
    p.add_argument("--analog-steer", action="store_true", help="steer with a virtual Xbox pad (needs vgamepad + ViGEmBus)")
    p.add_argument("--reward", choices=["distance", "upstream"], default="distance", help="distance: track progress is the reward (default), upstream: original speed-along-the-line reward")
    p.add_argument("--travel-weight", type=float, help="reward per 10 m of track progress (params.json)")
    p.add_argument("--mistake-penalty", type=float, help="penalty per step off the line / not progressing (params.json)")
    p.add_argument("--respawn-penalty", type=float, help="penalty for a forced respawn or give-up (params.json)")
    p.add_argument("--finish-bonus", type=float, help="bonus for finishing the track (params.json)")
    p.add_argument("--master-learn", action="store_true", help="you drive, the AI watches and records your runs as demonstrations (toggle later in the viewer)")
    p.add_argument("--no-master-learn", action="store_true", help="force master-learn off (e.g. when resuming a run that had it on)")
    p.add_argument("--demos", metavar="RUN|FILE", help="load the demonstrations of another run (run name or demos.pt)")
    p.add_argument("--no-viewer", action="store_true", help="don't serve the live viewer")
    p.add_argument("--viewer-port", type=int, default=2014, help="viewer port (default 2014: http://127.0.0.1:2014)")
    p.add_argument("--no-fixed-period", action="store_true", help="upstream timing: sleep the full timestep after each action (period = timestep + processing)")
    p.add_argument("--buffer", type=int, default=8192, help="replay buffer capacity (default 8192)")
    p.add_argument("--batch-size", type=int, help="learner batch size (params.json, default 32)")
    p.add_argument("--burnin", type=int, default=2048, help="experiences collected before learning starts (default 2048)")
    p.add_argument("--lr", type=float, default=3e-4, help="base learning rate (default 3e-4)")
    p.add_argument("--device", default=os.getenv("TMENV_DEVICE", "cuda:0"))
    p.add_argument("--websocket", action="store_true", help="publish live actions/steps on ws://127.0.0.1:2013 (aifront overlay)")
    p.add_argument("--wandb", action="store_true", help="log to Weights & Biases (TMLEARN_WANDB_PROJECT, TMLEARN_WANDB_ENTITY)")
    p.add_argument("--wandb-group", help="wandb training group to resume")
    p.add_argument("--wandb-agent", default="agent-latest.pth", help="wandb agent file to load when resuming")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation before a new training")
    return p.parse_args(argv)


def make_env(args, name="tmai1", window_x=0, window_y=0):
    env = Tmenv(
        name=name,
        width=args.width,
        height=args.height,
        timestep=TIMESTEP,
        action_handler=DiscreteActionHandler(),
        device=args.device,
        window_x=window_x,
        window_y=window_y,
        fixed_period=not args.no_fixed_period,
        game_kwargs=dict(
            port=args.port,
            launch=args.launch,
            analog_steer=args.analog_steer,
            resize_window=not args.no_resize,
            steal_focus=not args.no_focus_steal,
        ),
    )
    env = RotationEnvWrapper(env)
    env = TrajectoryEnvWrapper(env, minimum_speed=7, max_distance=50)
    env = TrajectoryDoneWrapper(
        env,
        max_mistake_duration=4,
        respawn_sequence=["launched", "standing"] * 2,
        give_up_before_first_cp=False,
    )
    if args.reward == "distance":
        env = TrackDistanceRewardWrapper(env, penalty_threshold=10.0)  # weights come from params.json
    else:
        env = TrajectoryTravelRewardWrapper(
            env,
            mistake_reward=-50 / 3.6,
            discount_factor=DISCOUNT_FACTOR,
            penalty_threshold=10.0,
        )
    env = VisualState(env, shape=(270, 480), keep_uint8=True)
    env = TrajectoryState(env, nb_positions=8, spacing=50)
    env = AlignedState(env)
    env = WheelState(env)
    env = EpisodeInfoWrapper(env)
    env = TelemetryState(env)
    return env


def build_training(args):
    envs = L(make_env(args))

    if args.map:
        map_scheduler = OneMapScheduler(args.map)
    else:
        maps_uid = campaigns_maps_uid(official_campaigns()[: args.campaigns], slice(args.maps_per_campaign))
        logging.info(f"Map schedule: {len(maps_uid)} maps from {args.campaigns} official campaigns")
        map_scheduler = MapScheduler(maps_uid)

    obs_space = envs[0].observation_space
    model = DuelingNet(
        model=StateCatNet(
            visual=TimmModel("regnetx_002", input_dim=obs_space["visual"].shape, positional=True),
            telemetry=Flatten(obs_space["telemetry"].shape),
            trajectory=Flatten(obs_space["trajectory"].shape),
            aligned=Flatten(obs_space["aligned"].shape),
            wheel=Conv1dFlat(obs_space["wheel"].shape, hidden=16),
        ),
        hidden=[512, 256],
        output_dim=envs[0].action_space.n,
        p=0.1,
    )
    model.apply(init_weights)

    agent = DqnAgent(
        model,
        exploration=RankSoftmaxExploration(),
        device=args.device,
        gamma=DISCOUNT_FACTOR,
    )
    replay_buffer = PrioritizedReplayBuffer(capacity=args.buffer, device=args.device)

    collector_cbs = [
        partial(TelemetryTimeoutRecoverCallback, 0.5),
        partial(MemoryFullRecoverCallback, 94.0),
        LagCallback,
        partial(IgnoreLaggyStepCallback, TIMESTEP * 2),
        IgnoreUnfocusedStepCallback,
        IgnoreIdleDemoCallback,
        partial(
            ExplorationSwitcherCallback,
            [
                EpsilonGreedyExploration(0.2),
                RankSoftmaxExploration(0.9),
                EpsilonGreedyExploration(0.1),
                RankSoftmaxExploration(1.0),
                EpsilonGreedyExploration(0.05),
                RankSoftmaxExploration(1.1),
                EpsilonGreedyExploration(0.02),
                EpsilonGreedyExploration(0.01),
                NoExploration(),
                NoExploration(),
            ],
        ),
        IgnoreUserRestartCallback,
    ]
    if args.reward == "upstream":
        # Upstream never learned from forced respawns / give-ups; the distance reward learns their penalty
        collector_cbs.append(IgnoreRespawnAndUnfinished)

    base_lr = args.lr
    training_cbs = [
        ExperienceTimeoutCallback(5 * 60),
        LrSchedulerCallback(
            combine_scheds(
                [0.01 / 103.01, 3 / 103.01, 100 / 103.01],
                [SchedCos(base_lr / 100, base_lr), SchedCos(base_lr, base_lr / 10), SchedExp(base_lr / 10, base_lr / 1000)],
            ),
            max_time=103.01 * 24 * 3600,
        ),
    ]

    overrides = dict(travel_weight=args.travel_weight, mistake_penalty=args.mistake_penalty,
                     respawn_penalty=args.respawn_penalty, finish_bonus=args.finish_bonus,
                     batch_size=args.batch_size)
    if args.master_learn:
        overrides["master_learn"] = True
    if args.no_master_learn:
        overrides["master_learn"] = False
    overrides = {k: v for k, v in overrides.items() if v is not None}

    return Training(
        map_scheduler=map_scheduler,
        envs=envs,
        agent=agent,
        replay_buffer=replay_buffer,
        session_scheduler=SessionScheduler(nb_episode=args.episodes_per_map),
        collector_cbs=collector_cbs,
        training_cbs=training_cbs,
        batch_size=args.batch_size or 32,
        burnin=args.burnin,
        online=args.wandb,
        websocket=args.websocket,
        wandb_project=os.getenv("TMLEARN_WANDB_PROJECT"),
        wandb_entity=os.getenv("TMLEARN_WANDB_ENTITY"),
        wandb_load_group=args.wandb_group,
        wandb_load_agent=args.wandb_agent,
        run_dir=args.run_dir,
        resume=args.resume,
        viewer=not args.no_viewer,
        viewer_port=args.viewer_port,
        params_overrides=overrides,
        demos=args.demos,
    )


def restore_run_config(args):
    "On --resume, settings not given on the command line come from the run's run_config.json."
    path = Path(args.run_dir) / args.resume / "run_config.json"
    if not path.exists():
        return
    try:
        saved = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as e:
        logging.warning(f"Ignoring unreadable {path}: {e}")
        return
    defaults = parse_args([])
    restored = {}
    for key in RUN_CONFIG_KEYS:
        if key in saved and getattr(args, key) == getattr(defaults, key) and saved[key] != getattr(args, key):
            setattr(args, key, saved[key])
            restored[key] = saved[key]
    if restored:
        logging.info(f"Resuming with the run's settings: {restored}")


def save_run_config(args, save_dir):
    path = Path(save_dir) / "run_config.json"
    path.write_text(json.dumps({key: getattr(args, key) for key in RUN_CONFIG_KEYS}, indent=2), encoding="utf-8")


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(
        format="[%(asctime)s][%(process)d][%(levelname)s]: %(message)s",
        datefmt="%d-%b-%y][%H:%M:%S",
        level=logging.INFO,
    )
    if args.resume is not None:
        restore_run_config(args)
    # Fixed input sizes: let cuDNN pick the fastest kernels
    torch.backends.cudnn.benchmark = True
    torch.backends.cuda.matmul.allow_tf32 = torch.backends.cudnn.allow_tf32 = True
    if args.resume is None and args.wandb_group is None and not args.yes:
        if input("You're starting a new training. Continue? (y/n): ").lower() not in ["y", "yes"]:
            print("Exiting.")
            return
    training = build_training(args)
    save_run_config(args, training.save_dir)
    training.fit()


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
