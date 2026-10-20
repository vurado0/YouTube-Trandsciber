# Transcript Study

Paste a YouTube link, get a time-synced transcript you can actually study from.
Built for learning **English**, **German** and **Japanese**.

It runs entirely on your own machine — there is no account, no API key and no
upload. The only thing that leaves your laptop is the request to YouTube.

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

## How a video gets transcribed

1. `yt-dlp` is asked what caption tracks the video has.
2. If a track exists in the language you picked, it is downloaded as `json3` —
   YouTube's caption format, which carries per-word timings for automatic
   captions. Machine-translated tracks are skipped on purpose: a German track
   auto-translated from English reads badly and teaches you the wrong phrasing.
3. Caption fragments get merged into sentence-sized lines, because YouTube cuts
   them into two-second scraps that are hard to read.
4. If there is no usable track, the audio is downloaded, converted to 16 kHz mono
   with `ffmpeg`, and run through `faster-whisper`.
5. Japanese transcripts are tokenised with MeCab (`fugashi` + `unidic-lite`) to
   get word boundaries and readings, and the readings are aligned to the kanji so
   the okurigana stays out of the ruby text.
6. The result is cached in `cache/` so reopening a video is instant.

## Project layout

```
backend/
  app.py          FastAPI server, job queue, caching
  captions.py     yt-dlp caption fetching, json3 parsing, sentence chunking
  whisper_asr.py  offline speech-to-text fallback
  japanese.py     tokenisation and furigana alignment
frontend/
  index.html      the whole UI
  app.js          player sync, word list, exports
  style.css       light and dark themes
```

No build step and no frontend framework — edit a file, reload the page.

## Known limits

* **Only you can use it.** It listens on `127.0.0.1` and is not hardened for the
  open internet. Keep it local.
* **Automatic captions are imperfect.** They lack punctuation on some channels
  and mishear names. For serious study, prefer videos with real subtitles.
* **Whisper is slow on a CPU.** Roughly real-time on Apple Silicon with the
  `small` model, so a 20-minute video takes about 20 minutes. It runs once per
  video and is then cached. Change `MODEL_SIZE` in `backend/whisper_asr.py` to
  `base` for speed or `medium` for accuracy.
* **Age-restricted and private videos won't load.** yt-dlp cannot reach them
  without signing in.
* Downloading audio from YouTube may conflict with its Terms of Service. The
  caption path, which is what you will use most of the time, does not download
  any media.

## Licence

MIT.
