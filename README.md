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
* **Saves the video** as MP4, or just the audio as MP3, for studying offline.

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

This needs a **persistent container host** — Fly.io, Railway, Render, or any box
that can run Docker.

```bash
docker build -t transcript-study .
docker run -p 8000:8000 -v transcript-data:/data transcript-study
```

### Fly.io

App names are globally unique, so pick your own and keep `--ha=false` — the
default creates two machines, which cannot share one volume.

```bash
fly auth login
fly launch --copy-config --no-deploy --ha=false --name your-unique-name
fly volumes create transcript_data --size 1 --region fra --yes
fly deploy
fly open
```

`--no-deploy` on the first command lets you create the volume before the machine
looks for it. Match `--region` to `primary_region` in `fly.toml`.

**Costs, as of October 2026.** Fly has no free tier for new organisations. New
accounts get a trial of 2 hours of machine runtime or 7 days, whichever runs out
first, and no card is needed to start it; after that a card is required. A
shared-cpu-1x/1 GB machine is $6.70 a month running continuously, but `fly.toml`
sets `auto_stop_machines`, so it sleeps when idle and you pay only for the time
it serves requests — a stopped machine is billed for its root filesystem at
$0.15/GB/month, and the volume at $0.15/GB/month whether running or not. For
light personal use expect well under a dollar a month; the 1.2 GB image makes
the idle floor a few cents.

For offline transcription on the server, set `WITH_WHISPER = "1"` in
`fly.toml`'s `[build.args]` and give the machine more memory — 1 GB is not
enough for the `small` model:

```bash
fly scale memory 2048
```

### It does not work on Vercel

Serverless is the wrong shape for this, and the entrypoint error you get first is
the least of it:

* Transcription runs as a background job that the browser polls. Serverless
  functions are frozen the moment they return a response, and the next poll can
  land on a different instance, so the job never finishes.
* `unidic-lite`, the Japanese dictionary, is 248 MB on its own — the function
  size limit is 250 MB.
* Whisper needs an ffmpeg binary, a ~500 MB model and minutes of CPU, against a
  timeout measured in seconds.
* YouTube rate-limits and bot-blocks datacenter IPs, which breaks even the
  lightweight caption path.

That last point applies to *any* host, not just Vercel. Expect a deployed
instance to hit "Sign in to confirm you're not a bot" sooner or later.

### Configuration

All of these are environment variables. The defaults in `Dockerfile` and
`fly.toml` are tuned for a shared instance; running locally everything is on.

| Variable | Default (local / container) | What it does |
| --- | --- | --- |
| `ENABLE_WHISPER` | on / **off** | Offline transcription for caption-less videos |
| `ENABLE_DOWNLOADS` | on / **off** | The MP4 and MP3 buttons |
| `MAX_CONCURRENT_JOBS` | 2 | Jobs running at once; the rest queue |
| `RATE_LIMIT_PER_HOUR` | 40 | Requests per IP per hour, 0 to disable |
| `MAX_DURATION_SECONDS` | 0 / 2700 | Reject videos longer than this, 0 for no limit |
| `TRUST_PROXY` | off / **on** | Read the client IP from the proxy header |
| `WORK_DIR` | `./cache` | Where transcripts and prepared files live |
| `PORT` | 8000 | Port to listen on |

**Downloads are off by default in the container on purpose.** A publicly
reachable YouTube downloader will likely breach your host's terms of service,
and it gets the instance IP-blocked by YouTube much faster than caption fetching
does. Set `ENABLE_DOWNLOADS=1` if you accept that. The app has no login, so
anyone with the URL can use whatever you switch on.

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
  downloads.py    MP4 and MP3 export
  japanese.py     tokenisation and furigana alignment
frontend/
  index.html      the whole UI
  app.js          player sync, word list, exports, downloads
  style.css       light and dark themes
Dockerfile        container image for a persistent host
fly.toml          Fly.io deployment config
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
* Downloading media from YouTube may conflict with its Terms of Service. The
  caption path, which is what you will use most of the time, downloads no media.

## Licence

MIT.
