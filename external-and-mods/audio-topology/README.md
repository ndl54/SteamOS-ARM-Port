# Audio topologies

AudioReach topology sources for the DSP's audio graphs, and the blobs built
from them that the images install over the kernel package's copies.

| Device | Source | Installed as |
| --- | --- | --- |
| AYN Odin 3 | `sm8750/SM8750-AYN.m4` | `/usr/lib/firmware/qcom/sm8750/SM8750-AYN-tplg.bin` |

The Odin 3 graph is the one ROCKNIX ships (speakers on SECONDARY MI2S SD0,
WCD939x headphones and headset mic) plus MultiMedia4 to DISPLAY_PORT_RX_0, so
the graph has a DisplayPort playback route over USB-C. This is not USB Audio
Class or an analog USB-C headset route, and does not establish working sound
on hardware. The existing three PCM records and routes match the pinned
ROCKNIX blob; the parsed existing module tokens differ only in port counts
(tokens 204/205). See the integration review for the binary checks and limits.

The supplied blob is kept unchanged from upstream. The generator revision
used to produce it was not recorded; the commands below are an upstream
rebuild recipe, not a pinned or verified reproducible build. Review 077 did
not run them. Loading the graph still depends on compatible ADSP firmware,
the kernel DP backend/HDMI codec, an enabled display link and sink audio
capabilities. Hotplug and suspend/resume require device validation.

Rebuild (the build VM, any Ubuntu with alsa-utils and m4):

```sh
git clone https://git.codelinaro.org/linaro/qcomlt/audioreach-topology.git
m4 -I audioreach-topology sm8750/SM8750-AYN.m4 > SM8750-AYN.conf
alsatplg -c SM8750-AYN.conf -o sm8750/SM8750-AYN-tplg.bin
```

The "undefined widget/stream" warnings are expected: the back ends come from
the kernel's DAI links.
