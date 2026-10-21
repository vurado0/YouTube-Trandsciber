# Transcript Study

Paste a YouTube link, get a time-synced transcript you can actually study from.
Built for learning **English**, **German** and **Japanese**.

Runs on your own machine by default — no account, no API key, nothing uploaded.
The only thing that leaves your laptop is the request to YouTube.

![Study view](docs/screenshot-ja.png)

## What it does

* **Pulls the real captions.** If the video has subtitles — the creator's own or
  YouTube's automatic ones — it uses those. That takes a second or two.
* **Falls back to offline speech-to-text.** No captions? The audio is transcribed
  locally with Whisper. Nothing is sent to a third party.
* **Keeps the text in sync.** The current line is highlighted as the video plays,
  the transcript scrolls along with it, and clicking a line jumps the video there.
* **Loops a single line** so you can replay a sentence until you catch every word.
* **Builds a word list.** Click any word to save it together with the sentence it
  came from and its timestamp. Export the list as a CSV that drops straight into
  Anki.
* **Furigana for Japanese.** The Japanese text is split into real words — not
  characters — and every kanji gets its reading above it. Toggle the readings off
  when you want to test yourself.
* **Hide-the-text mode** for pure listening practice: the transcript blurs out and
  only the line currently being spoken stays readable.

## Setup

You need [Homebrew](https://brew.sh) and Python 3.12 or newer.

```bash
brew install ffmpeg python@3.12
git clone https://github.com/vurado0/YouTube-Trandsciber.git
cd YouTube-Trandsciber
./setup.sh --with-whisper
```

`--with-whisper` installs the offline transcriber, roughly 300 MB of
dependencies plus a ~500 MB speech model that downloads the first time you
actually need it. Leave the flag off if you only ever study videos that already
have captions — everything else works the same, and you can add it later by
re-running the command.

## Running it

```bash
./run.sh
```

That starts a local server and opens <http://localhost:8000>. Paste a link,
pick the spoken language (or leave it on auto-detect), and press Transcribe.

To use a different port: `PORT=9000 ./run.sh`.

## Keyboard shortcuts

| Key | What it does |
| --- | --- |
| `Space` | Play / pause |
| `←` `→` | Previous / next line |
| `R` | Loop the current line |
| `F` | Follow along on/off |
| `H` | Hide the text (listening mode) |
| `/` | Jump to the search box |

## Deploying it

What you get depends on where you put it:

| | Local | Vercel | Docker host |
| --- | --- | --- | --- |
| Captions (en/de/ja) | yes | yes | yes |
| Furigana | yes | yes | yes |
| Word list, exports | yes | yes | yes |
| Offline Whisper | yes | **no** | optional |

### Vercel

The app detects Vercel and switches to a single-request mode: the transcript is
fetched and returned inside the one HTTP request, because a serverless function
is frozen as soon as it responds and could never finish a job the browser polls
for. A 24-minute Japanese video, tokenised and with furigana, takes about 1.7
seconds and comes back as roughly 430 KB.

```bash
vercel          # preview deployment
vercel --prod   # production
```

`pyproject.toml` points Vercel at `main:app`, and `vercel.json` sets
`SERVERLESS=1` and a 60-second function limit. Nothing else to configure.

**What does not work there.** Whisper needs an ffmpeg binary, a ~500 MB model
and minutes of CPU, against a 60-second function. It keeps working locally from
the same codebase.

**YouTube blocks it, and this is confirmed, not theoretical.** A deployment to
Vercel serves the app correctly but every caption request comes back with:

> Sign in to confirm you're not a bot.

YouTube refuses requests from datacenter IP ranges, and Vercel runs on them.
Nothing in the app can fix this — it is a property of where the request comes
from. The identical code on a laptop works every time, because the request
comes from a home connection.

Two ways round it, both with real costs:

* **Cookies.** Set `YTDLP_COOKIES` to the contents of a Netscape-format cookie
  file exported from a browser signed in to YouTube. Understand what that
  means: anyone who can read your environment variables has a live session for
  that Google account, YouTube may suspend an account it sees being automated,
  and the cookies expire after a few weeks. Use a throwaway account, never your
  main one. Full steps under [Setting up cookies](#setting-up-cookies).
* **A residential proxy**, which costs money and is what the commercial
  transcript services are quietly paying for.

If neither appeals, run it locally — that path has no blocking problem at all,
and is what this tool is really built for.

### Using it from your phone

The thing a cloud deployment cannot do is reach YouTube, because requests from
datacenter IPs get blocked. A tunnel sidesteps that entirely: the app stays on
your machine, so YouTube still sees your home connection, and you get a public
HTTPS URL to open on a phone.

```bash
brew install cloudflared
./share.sh
```

It starts the server if it is not already running, opens the tunnel, and prints
a `https://….trycloudflare.com` address. Open that on your phone. Ctrl-C stops
sharing. Everything works over it — Whisper, furigana, exports.

Two things to know. The address is public to anyone who has it, and the app has
no login, so whoever opens it can run transcriptions on your laptop and
transcribe through your connection; it is unguessable, but do not post it
anywhere. And it is **a new address every run** — quick tunnels cannot keep
theirs, and a stopped one is gone for good.

#### Using your own domain

For a fixed, readable address like `study.example.com`, you need a domain whose
DNS is hosted on Cloudflare. The tunnel itself is free on every Cloudflare plan;
the domain is the only cost, from a few euros a year. Registering it at
Cloudflare Registrar is the least work, because the DNS is then already in the
right place — otherwise point your registrar's nameservers at Cloudflare first.

One-time setup:

```bash
cloudflared tunnel login                  # pick your domain in the browser
cloudflared tunnel create transcript-study
cloudflared tunnel route dns transcript-study study.example.com
```

After that, every time:

```bash
TUNNEL_HOSTNAME=study.example.com ./share.sh
```

The address is now stable across restarts and reboots, and there is no
interstitial page. To have it come back by itself after a reboot, install
cloudflared as a service with `cloudflared service install`.

### Setting up cookies

Only worth doing for a hosted instance; running locally never needs it.

1. **Make a throwaway Google account.** Never use your real one — YouTube
   suspends accounts it catches being automated, and the exported cookies are a
   live session for whatever account you use.
2. **Open a private/incognito window**, sign in to youtube.com with that
   account, and watch a few seconds of any video.
3. **Export the cookies** with a Netscape-format cookie extension (for example
   "Get cookies.txt LOCALLY"), restricted to youtube.com. You want the
   tab-separated `cookies.txt` format, not JSON.
4. **Close the private window without signing out.** Signing out invalidates
   the cookies you just exported; closing the window leaves them valid.
5. **Set it on the host.** From the project directory:

   ```bash
   vercel env add YTDLP_COOKIES production < cookies.txt
   vercel --prod
   ```

   Or paste the file's contents into the variable in the Vercel dashboard under
   Settings → Environment Variables. The leading `# Netscape HTTP Cookie File`
   line is added for you if your paste loses it.
6. **Delete your local `cookies.txt`** afterwards.

Expect to repeat this every few weeks when the session expires, and to find
the account suspended eventually. If the value is not a real cookie file the
app says so rather than failing with the bot-check error.

### Docker, for everything at once

A persistent container keeps every feature, Whisper included.

```bash
docker build -t transcript-study .
docker run -p 8000:8000 -v transcript-data:/data transcript-study
```

On Fly.io, edit the `app` name in `fly.toml`, then:

```bash
fly auth login
fly launch --copy-config --no-deploy --ha=false --name your-unique-name
fly volumes create transcript_data --size 1 --region fra --yes
fly deploy
```

`--ha=false` matters: the default creates two machines, and two machines cannot
share one volume. Note that Fly has **no free tier** for new organisations as of
October 2026 — a trial of 2 hours of machine runtime or 7 days, then a card is
required. With `auto_stop_machines` the instance sleeps when idle, so light use
costs well under a dollar a month, but it is not free.

For Whisper on the server set `WITH_WHISPER = "1"` in `fly.toml`'s
`[build.args]` and run `fly scale memory 2048` — 1 GB is not enough for the
`small` model.

### Configuration

All of these are environment variables. Vercel and the container set
shared-instance defaults; running locally everything is on.

| Variable | Default (local / deployed) | What it does |
| --- | --- | --- |
| `SERVERLESS` | off / **on** (auto on Vercel) | One-request mode, no job polling |
| `ENABLE_WHISPER` | on / **off** | Offline transcription for caption-less videos |
| `MAX_CONCURRENT_JOBS` | 2 | Jobs running at once; the rest queue |
| `RATE_LIMIT_PER_HOUR` | 40 | Requests per IP per hour, 0 to disable |
| `MAX_DURATION_SECONDS` | 0 / 2700 | Reject videos longer than this, 0 for no limit |
| `TRUST_PROXY` | off / **on** | Read the client IP from the proxy header |
| `YTDLP_COOKIES` | unset | Cookie file path, or its contents, to get past YouTube's bot check |
| `WORK_DIR` | `./cache` | Where transcripts and prepared files live |
| `PORT` | 8000 | Port to listen on |

The app has no login, so anyone with the URL can use whatever you switch on.

Japanese needs a MeCab dictionary. `unidic-lite` (248 MB, better readings) is
used when present; `ipadic` (51 MB) works as a smaller substitute and gives
better dictionary forms for verbs. The whole Vercel bundle with unidic-lite is
about 301 MB, inside the 500 MB function limit.

## How a video gets transcribed

1. The link is reduced to its 11-character video id and a clean watch URL is
   rebuilt from it. User input never reaches yt-dlp directly — otherwise it
   would happily fetch anything, including addresses on the host's own network.
2. `yt-dlp` is asked what caption tracks the video has.
3. If a track exists in the language you picked, it is downloaded as `json3` —
   YouTube's caption format, which carries per-word timings for automatic
   captions. Machine-translated tracks are skipped on purpose: a German track
   auto-translated from English reads badly and teaches you the wrong phrasing.
4. Caption fragments get merged into sentence-sized lines, because YouTube cuts
   them into two-second scraps that are hard to read.
5. If there is no usable track, the audio is downloaded, converted to 16 kHz mono
   with `ffmpeg`, and run through `faster-whisper`.
6. Japanese transcripts are tokenised with MeCab (`fugashi` + `unidic-lite`) to
   get word boundaries and readings, and the readings are aligned to the kanji so
   the okurigana stays out of the ruby text.
7. The result is cached so reopening a video is instant.

## Project layout

```
backend/
  app.py          FastAPI server, job queue, limits, caching
  captions.py     yt-dlp caption fetching, json3 parsing, sentence chunking
  whisper_asr.py  offline speech-to-text fallback
  japanese.py     tokenisation and furigana alignment
frontend/
  index.html      the whole UI
  app.js          player sync, word list, exports
  style.css       light and dark themes
main.py           entrypoint for serverless (Vercel) imports
pyproject.toml    Vercel entrypoint config
vercel.json       Vercel function settings
Dockerfile        container image for a persistent host
fly.toml          Fly.io deployment config
share.sh          put the local app on a public URL via Cloudflare
```

No build step and no frontend framework — edit a file, reload the page.

## Known limits

* **There is no login.** Anything you switch on is available to anyone who has
  the URL. Keep the instance private, or put it behind your host's access
  control.
* **Automatic captions are imperfect.** They lack punctuation on some channels
  and mishear names. For serious study, prefer videos with real subtitles.
* **Whisper is slow on a CPU.** Roughly real-time on Apple Silicon with the
  `small` model, so a 20-minute video takes about 20 minutes. It runs once per
  video and is then cached. Change `MODEL_SIZE` in `backend/whisper_asr.py` to
  `base` for speed or `medium` for accuracy.
* **Age-restricted and private videos won't load.** yt-dlp cannot reach them
  without signing in.

## Licence

MIT.
