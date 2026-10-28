# Third-party notices

spritewright itself is licensed under the [MIT License](LICENSE). It includes or adapts the following
third-party work, and depends on the packages listed at the end.

## Alois Zingl - rasterizing algorithms (MIT)

The ellipse rasterizer in `spritewright/canvas.py` (`_ellipse_points`) is adapted from the
rectangle-bounded midpoint ellipse routine (`plotEllipseRect`) by Alois Zingl, described in "A
Rasterizing Algorithm for Drawing Curves" (Technical Report, Vienna, 2012) and on the author's page
"The Beauty of Bresenham's Algorithm" (<http://members.chello.at/easyfilter/bresenham.html>). The
author's pages describe the code as free software under the terms of the MIT License; it is adapted here
under those terms. The line routine follows the integer Bresenham formulation presented there.

## Robert Penner - easing equations

The easing functions in `spritewright/anim.py` (in particular `ease_out_back` with the overshoot constant
1.70158 and the bounce curve) are based on Robert Penner's easing equations, which are distributed under
the following license:

```text
TERMS OF USE - EASING EQUATIONS

Open source under the BSD License.

Copyright (c) 2001 Robert Penner
All rights reserved.

Redistribution and use in source and binary forms, with or without modification, are permitted
provided that the following conditions are met:

  * Redistributions of source code must retain the above copyright notice, this list of conditions
    and the following disclaimer.
  * Redistributions in binary form must reproduce the above copyright notice, this list of conditions
    and the following disclaimer in the documentation and/or other materials provided with the
    distribution.
  * Neither the name of the author nor the names of contributors may be used to endorse or promote
    products derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR
IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND
FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS
BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
(INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## PICO-8 palette - Lexaloffle Games (CC0)

`spritewright/palettes/pico-8.hex` contains the 16-colour PICO-8 palette by Lexaloffle Games. Lexaloffle
releases the palette under CC0 1.0 Universal (public domain dedication),
<https://creativecommons.org/publicdomain/zero/1.0/>. The same colours are used by the bundled example
in `examples/`. PICO-8 is a trademark of Lexaloffle Games; spritewright is not affiliated with or endorsed
by Lexaloffle Games.

## Contributor Covenant (CC BY 4.0)

`CODE_OF_CONDUCT.md` is adapted from the Contributor Covenant, version 2.1
(<https://www.contributor-covenant.org/version/2/1/code_of_conduct.html>), licensed under the Creative
Commons Attribution 4.0 International License (<https://creativecommons.org/licenses/by/4.0/>). The
reporting contact was changed.

## Runtime dependencies (not bundled)

These packages are installed by pip as dependencies; they are not included in this repository.

| Package | License | Project |
|---|---|---|
| Pillow | MIT-CMU (Historical Permission Notice and Disclaimer) | <https://python-pillow.org> |
| NumPy | BSD-3-Clause | <https://numpy.org> |

Development and CI additionally use `build` and `hatchling` (both MIT) to build the package; they are not
runtime dependencies.
