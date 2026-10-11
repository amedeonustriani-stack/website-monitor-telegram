# website-monitor-telegram

A small Python bot that watches a web page and sends you a Telegram message when
a new item matches your rules: a keyword, a price range, anything you can
filter by.

- checks the page on a schedule
- keeps only the items that match your words and price limits
- sends the matches to you on Telegram
- remembers what it already sent, so you never get the same alert twice
- writes a CSV log of **every** item it saw and the reason it was kept or dropped

It is one file (`monitor.py`) and two libraries (`requests`, `beautifulsoup4`).

## Try it in two minutes, without touching a real website

```bash
pip install -r requirements.txt

# terminal 1: serve the fake demo page
cd demo
python -m http.server 8000

# terminal 2: run one check and print the result instead of sending it
python monitor.py --config demo/config.demo.json --once --dry-run
```

You will see one match printed, and a `demo/log.csv` file showing why the other two items were
dropped (wrong word, price above the limit). Add a new item to `demo/page.html`, run the command
again, and only the new item is handled.

## Use it on a real page

1. Copy `config.example.json` to `config.json`.
2. Fill in the page address and the CSS selectors that point at one item, its title, its price and
   its link. (In your browser: right click on an item, "Inspect", and look at the class names.)
3. Set your words and price limits.
4. Create a Telegram bot (see below) and set two environment variables.
5. Run it:

```bash
python monitor.py --config config.json            # runs forever, checks every interval
python monitor.py --config config.json --once     # one check, then exit
python monitor.py --config config.json --once --dry-run   # print matches, send nothing
```

The first real run only records what is already on the page, so you are not flooded with old
items. From then on you get the new ones. (Set `"send_existing_on_first_run": true` if you want
the opposite.)

### Config options

| key | what it does |
|---|---|
| `url` | the page to check |
| `item_selector` | CSS selector for one item on the page |
| `title_selector` | CSS selector for the title inside an item |
| `price_selector` | CSS selector for the price inside an item (optional) |
| `link_selector` | CSS selector for the link (defaults to the title) |
| `include_words` | the item must contain at least one of these words in its title |
| `exclude_words` | the item is dropped if it contains any of these |
| `min_price`, `max_price` | price limits, or `null` |
| `interval_minutes` | how often to check (never less than 5) |
| `state_file`, `log_file` | where it stores what it has seen, and the CSV log |

### Telegram setup

1. In Telegram, talk to `@BotFather`, send `/newbot`, and follow the questions. It gives you a
   **token**.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in your browser and find
   `"chat":{"id":123456789,...}`. That number is your **chat id**.
4. Set the two variables before running the bot:

```bash
# Linux / macOS
export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="123456789"

# Windows PowerShell
$env:TELEGRAM_BOT_TOKEN="123456:ABC..."
$env:TELEGRAM_CHAT_ID="123456789"
```

Keep the token private. It is read from the environment on purpose, so it never ends up in a file
or in your GitHub repository.

### Keeping it running

To get alerts while you sleep, the script has to keep running: leave it on a computer that stays
on, or run it on a small server. A scheduled task (Windows Task Scheduler, `cron`) with `--once` also works.

## What it does not do

- It reads the HTML the server sends. Pages that build their content with JavaScript may show up
  as "No items found"; those need a different tool.
- It does not log in to anything.
- It does not get around blocks. If a site answers 403 or 429, the site does not want automated
  visits: the bot reports it and does not try to work around it.
- It checks no more often than every 5 minutes, to be polite.

Use it only on pages whose terms allow automated access, and for personal alerts. Check the site's
rules and `robots.txt` first. You are responsible for how you use it.

## Need it adapted to your site?

I build custom versions of this bot: your website, your filters, several sites in one bot, and a
setup that runs 24/7. The first step is free, because I look at your page and tell you honestly
whether it can be done.

**[See my Fiverr gig](https://www.fiverr.com/s/lrrbBDa)**

## License

MIT, see `LICENSE`.
