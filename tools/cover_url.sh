#!/bin/sh
# Print where the configurator is reachable right now.
#
# The public address comes from a Cloudflare quick tunnel, which mints a new
# name every time it starts, so it is read back out of the tunnel's log rather
# than written down anywhere.
printf 'this machine   http://localhost:8000\n'
ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
[ -n "$ip" ] && printf 'same network   http://%s:8000\n' "$ip"
url=$(grep -Eoh 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cover-tunnel.log /tmp/cf.log 2>/dev/null | tail -1)
if [ -n "$url" ]; then printf 'anywhere       %s\n' "$url"
else printf 'anywhere       (tunnel not running: launchctl kickstart -k gui/$(id -u)/com.cover.tunnel)\n'; fi
