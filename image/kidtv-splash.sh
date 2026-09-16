#!/bin/sh
# Show the (personalised, if available) splash picture on the framebuffer.
IMG=/var/lib/kidtv/splash.png
[ -f "$IMG" ] || IMG=/opt/kidtv/kidtv/assets/splash.png
command -v fbi >/dev/null 2>&1 || exit 0
exec /usr/bin/fbi -T 1 -d /dev/fb0 --noverbose -a "$IMG" >/dev/null 2>&1 &
exit 0
