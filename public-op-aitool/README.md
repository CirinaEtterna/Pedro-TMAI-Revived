# AITool Openplanet Plugin
> Openplanet plugin for Trackmania 2020 that communicate with the outside world via socket and server to load map, save ghost and send telemetry.

## Disclaimer

This project is not actively maintained, may be outdated, and support is
not guaranteed. For potential assistance, try reaching out on
[Discord](https://discord.gg/cQyC4ydY).

**About PedroAI**  
op-aitool is part of the PedroAI project
([trackmania-ai](https://github.com/trackmania-ai) on github), which I
began in April 2020. I streamed AI training on
[Twitch](https://www.twitch.tv/pedroaitm) from April 2021 to September
2023. I’ve since moved on to other projects and decided to open-source
PedroAI. For more details, check the
[blog](https://www.trackmania.ai/blog/).


## Install

Clone the repository from your OpenPlanet `Plugins` folder.

```
git clone https://github.com/trackmania-ai/public-op-aitool.git AITool
```

## Build

```
zip -r AITool.op *.as info.toml *.sig
```

## Zip for signing request

```
zip -r AITool.zip *.as info.toml
```