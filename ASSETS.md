# Assets and credits

## Images in `art/`: CC0 1.0, AI-generated

All 16 images (8 portraits, 8 squad crests) were generated locally with an open-weight image model,
then post-processed by the scripts in `scripts/art/`. They are dedicated to the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) (full text: `art/LICENSE`).
Use them for anything; no credit required.

AI-generated images may not be eligible for copyright in some jurisdictions. CC0 states our intent
plainly either way. This file is a record of how the images were made, not legal advice.

### How they were made

| Step | What | Where |
|---|---|---|
| 1. Generate | Text-to-image only. No reference image, photo or screenshot was used as input (empty latent). | `scripts/art/generate.py` + `scripts/art/prompts.json` (exact prompt, seed, sampler, batch index of every image) |
| 2. Portraits | Crop to 8:9, cut the character out of its plain background, paint a new background (glow, rays, bokeh, stars), add a silver frame | `scripts/art/decor.py` |
| 3. Crests | The model draws a black silhouette only; the shield, colors and shadow are drawn by code | `scripts/art/crest_compose.py` |

Steps 2 and 3 reproduce `art/` byte-for-byte from the raw images. The raw images (16 PNGs, 6.5 MB) are kept
out of the repository so plugin installs stay small. Each GitHub release attaches them as
`party-hud-raw-art.tar.gz`; extract it into `scripts/art/` to rerun steps 2 and 3 without ComfyUI, or regenerate
them with step 1. Regenerating on different hardware or ComfyUI versions may give slightly different pictures.
Prompts describe generic fantasy roles ("swordsman", "cleric", "lion head silhouette") and do not name
any existing game, character or artist.

### Models (all run locally through ComfyUI)

| Model | File | License | Source |
|---|---|---|---|
| FLUX.2 [klein] 4B (Black Forest Labs), step-distilled | `flux-2-klein-4b.safetensors` | Apache-2.0 | [model card](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B), [license table](https://github.com/black-forest-labs/flux2#readme) |
| Qwen3-4B (text encoder) | `qwen_3_4b.safetensors` | Apache-2.0 | [model card](https://huggingface.co/Qwen/Qwen3-4B) |
| FLUX.2 autoencoder (VAE) | `flux2-vae.safetensors` | Apache-2.0 | [flux2 README, "FLUX.2 autoencoder"](https://github.com/black-forest-labs/flux2#readme) |

The three files were downloaded from [Comfy-Org/flux2-klein](https://huggingface.co/Comfy-Org/flux2-klein)
(repackaged for ComfyUI, Apache-2.0). Note: the 9B [klein] models and FLUX.2 [dev] use the FLUX
Non-Commercial License; they were **not** used.

Tools: [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (GPL-3.0; the license covers the program,
not the images it produces), [Pillow](https://python-pillow.org/) and NumPy for post-processing.

## Icons

Icons are characters from [Nerd Fonts](https://www.nerdfonts.com/) (mostly Material Design Icons).
No font files are bundled; you need a Nerd Font installed. Nerd Fonts and its icon sets are
distributed under their own licenses (SIL OFL 1.1, MIT, Apache-2.0 and others; see the
[Nerd Fonts license](https://github.com/ryanoasis/nerd-fonts/blob/master/LICENSE)).

## Ideas borrowed

- Final Fantasy Resonance (Square Enix): playing it gave the idea of showing agents as party members with
  portraits, HP and SP. Only the idea was borrowed; the layout (a vertical sidebar of squads and cards) is party-hud's
  own. No names, art, icons or interface assets from the game are used, and the image prompts name no game.
  party-hud is not affiliated with or endorsed by Square Enix.
- [herdr](https://github.com/herdrdev/herdr) (Apache-2.0): agent status at a glance.
- [workmux](https://github.com/raine/workmux) (MIT): party-hud reads workmux's pane status
  (`@workmux_pane_status`) when present.
- The row/column diacritics for Kitty Unicode placeholders follow the
  [Kitty graphics protocol](https://sw.kovidgoyal.net/kitty/graphics-protocol/#unicode-placeholders) specification.

## Development

The code was written with AI coding assistants (Anthropic Claude via Claude Code), reviewed and
tested by the author.
