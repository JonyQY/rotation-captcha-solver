# Third-party components

The spincap orchestration, consensus gate, angle utilities, and adapters are
distributed under the MIT license in LICENSE.

Image orientation recognition is provided by **RightWayUp**, developed by
**ORTUS AI**, and is not a model trained by this project.

- Source: https://github.com/ortusaitech/rightwayup
- Package: https://pypi.org/project/rightwayup/
- Weights: https://huggingface.co/ortusai/rightwayup
- Upstream license: Apache-2.0 (source and model card).
- License text: https://github.com/ortusaitech/rightwayup/blob/main/LICENSE

RightWayUp and its model weights are not copied into this repository or wheel.
Installing the `model` extra installs the upstream package and its dependencies;
the upstream package downloads model weights on first use. Those components
retain their own licenses. spincap's MIT license does not replace them.

The optional Playwright package is maintained by Microsoft under Apache-2.0:
https://github.com/microsoft/playwright-python

This project is independent of ORTUS AI, Microsoft, and the websites referenced
by the optional adapters. No affiliation or endorsement is implied.
