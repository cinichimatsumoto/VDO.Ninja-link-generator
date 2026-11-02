# VDO.Ninja phone link generator

Generates VDO.Ninja phone links, OBS links, a Director link and QR codes for unmanned phone cameras.

- `index.html` is the web version. It is a single static file and runs entirely in the browser.
- `vdo_link_generator_gui.py` is the desktop version (Python + tkinter). It reads and writes the same settings format.

Settings and the room password are saved only in each visitor's own browser (or in `vdo_profile.json` for the desktop tool). `.gitignore` keeps that file out of the repository. Never commit it.
