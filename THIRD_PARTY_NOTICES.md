# Third-party notices

## Pixel Agents (office engine and pixel-art assets)

The Pixel Office UI (`office-ui/`, built into `peer_consult/office_dist/`) adapts the Canvas 2D office
engine and bundled sprites (characters, floors, walls, carpets, furniture, pets) from
[pixel-agents-hq/pixel-agents](https://github.com/pixel-agents-hq/pixel-agents) v1.5.0.

```
MIT License

Copyright (c) 2026 Pablo De Lucca

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

As credited upstream, the character sprites are based on
[Metro City Free Topdown Character Pack](https://jik-a-4.itch.io/metrocity-free-topdown-character-pack) by JIK-A-4.

Sprites under `office-ui/public/assets/generated/` are project-specific variants (agent characters,
emotes, carpets) in the same format and are distributed under the same terms.

## Runtime dependencies

The Python package depends on Typer, Click, Pydantic, Starlette, Uvicorn and websockets, and the
office UI bundle includes React, React DOM and Motion. Each is distributed under its own license
(MIT or BSD); see the respective projects.

## Trademarks

Claude and Claude Code are trademarks of Anthropic. Codex and OpenAI are trademarks of OpenAI.
Gemini and Antigravity are trademarks of Google. peer-consult is an independent project and is not
affiliated with or endorsed by any of them; the names are used only to identify the CLIs it drives.
