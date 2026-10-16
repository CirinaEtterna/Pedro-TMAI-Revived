"""Benchmark the DQN learner / actor on random states shaped like the real observations."""
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "public-tmlearn"))
from tmlearn.agent.dqn import DqnAgent  # noqa: E402
from tmlearn.neural import Conv1dFlat, DuelingNet, Flatten, StateCatNet, TimmModel, init_weights  # noqa: E402
from tmlearn.replay_buffer import PrioritizedReplayBuffer  # noqa: E402

import os  # noqa: E402

if os.getenv("BENCH_CUDNN"):
    torch.backends.cudnn.benchmark = True
if os.getenv("BENCH_TF32"):
    torch.backends.cuda.matmul.allow_tf32 = torch.backends.cudnn.allow_tf32 = True

dev = "cuda:0"
shapes = dict(visual=(3, 270, 480), telemetry=(66,), trajectory=(4, 8), aligned=(1,), wheel=(90, 4))
model = DuelingNet(
    model=StateCatNet(
        visual=TimmModel("regnetx_002", input_dim=shapes["visual"], positional=True),
        telemetry=Flatten(shapes["telemetry"]), trajectory=Flatten(shapes["trajectory"]),
        aligned=Flatten(shapes["aligned"]), wheel=Conv1dFlat(shapes["wheel"], hidden=16),
    ),
    hidden=[512, 256], output_dim=12, p=0.1,
)
model.apply(init_weights)
agent = DqnAgent(model, device=dev, gamma=0.95)


def state():
    s = {k: torch.rand(v, device=dev) for k, v in shapes.items() if k != "visual"}
    s["visual"] = torch.randint(0, 255, shapes["visual"], dtype=torch.uint8, device=dev)
    return s


rb = PrioritizedReplayBuffer(capacity=8192, device=dev)
states = [state() for _ in range(1025)]
for i in range(1024):
    rb._push(states[i], states[i + 1], i % 12, 0.1, False)
print(f"GPU memory after 1024 transitions: {torch.cuda.memory_allocated() / 2**30:.2f} GiB")

for _ in range(5):
    batch, idx, w = rb.sample(32)
    errors, _ = agent.fit_one_batch(batch, w)
torch.cuda.synchronize()
n = 100
t = time.perf_counter()
t_sample = 0
for _ in range(n):
    t0 = time.perf_counter()
    batch, idx, w = rb.sample(32)
    t_sample += time.perf_counter() - t0
    errors, _ = agent.fit_one_batch(batch, w)
    rb.update_priorities(idx, errors)
torch.cuda.synchronize()
dt = time.perf_counter() - t
print(f"learner: {n / dt:.1f} batches/s (sampling {t_sample / n * 1000:.1f} ms/batch)")

with torch.no_grad():
    for _ in range(5):
        agent.select_action(state())
    torch.cuda.synchronize()
    t = time.perf_counter()
    for _ in range(50):
        agent.select_action(state())
    print(f"actor: {(time.perf_counter() - t) / 50 * 1000:.1f} ms/action")
print(f"peak GPU memory: {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB")
