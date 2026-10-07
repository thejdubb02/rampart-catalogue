# Rampart catalogue

This is the add-on catalogue for [Rampart](https://github.com/thejdubb02/rampart), a desktop mail client. It holds themes, message templates and assistant prompts.

Rampart reads this catalogue only when you open it. It downloads `index.json`, shows the items, and installs the one you add.

## Adding an item

Put a theme in `themes/<id>.json`, a template in `templates/<id>.json`, or an assistant prompt in `prompts/<id>.json`. The id is the file name: it starts with a letter or digit, then uses lowercase letters, digits and hyphens, and is 2 to 41 characters long.

Run:

```bash
python3 tools/build_index.py
```

That checks the file and rewrites `index.json`. Open a pull request with both the new file and the updated index. The check fails if the index is stale.

## Data only

Every item is data. A theme is a set of colours. A template is a subject and a body. A prompt is a name and an instruction of up to 2,000 characters, and Rampart shows all of it before it is saved. A prompt with characters the reader cannot see (zero-width or direction-changing characters) is refused. Nothing here is code, and Rampart does not run what it downloads.

An add-on that ran code could read all your mail and your keys. This catalogue stays data so that cannot happen.
