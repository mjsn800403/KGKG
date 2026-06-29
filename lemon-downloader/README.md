# LEMON Manuals Downloader

Downloads every vehicle's offline `.zip` manual from a `lemon-manuals.org.ua`
Brand/Year page. Handles the site's "type **human**" verification automatically,
downloads 3 at a time, skips files already downloaded, and resumes safely.

## Run it

```bash
bash run.sh
```

It installs the dependencies, then asks for the link. Paste a Brand/Year URL, e.g.:

```
https://lemon-manuals.org.ua/Toyota/2025/
```

You can also pass the link and options directly:

```bash
bash run.sh "https://lemon-manuals.org.ua/Toyota/2025/"
bash run.sh "https://lemon-manuals.org.ua/Ford/2020/" --workers 3 --output-dir /root/downloads
```

### Options

| Option           | Default          | Meaning                                      |
|------------------|------------------|----------------------------------------------|
| `--workers N`    | `3`              | How many downloads run in parallel           |
| `--output-dir D` | `/root/downloads`| Where the `.zip` files go (as root)          |
| `--delay S`      | `1.0`            | Seconds to stagger between starting downloads |
| `--dry-run`      | off              | Just list the vehicles, download nothing      |

Files are saved under `<output-dir>/<Brand>_<Year>/`.

## On the server (long runs)

A full Brand/Year can be many large files. Run it inside `tmux` so it keeps
going if your SSH session drops:

```bash
tmux new -s lemon
mkdir -p /root/downloads
bash run.sh
# detach: Ctrl-b then d   |   reattach later: tmux attach -t lemon
```

## Notes

- Already-downloaded, valid `.zip` files are skipped on re-run. A corrupt/partial
  file is detected and re-downloaded automatically.
- Only downloads the single Brand/Year you point it at. For the *entire* LEMON
  database the site asks you to use their torrent instead (see the site's About page).
