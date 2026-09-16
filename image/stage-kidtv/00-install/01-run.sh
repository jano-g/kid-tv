#!/bin/bash -e
# Copy the repository into the image and run the shared provisioning script.
#
# In the GitHub Actions build only the stage directory is mounted into the
# pi-gen container, so the workflow bundles the checkout into
# 00-install/files/kidtv-src first. A local pi-gen build can use the repo
# directly (the stage lives in <repo>/image/stage-kidtv).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${HERE}/files/kidtv-src"
if [ ! -f "${SRC}/image/setup.sh" ]; then
  SRC="$(realpath "${HERE}/../../..")"
fi
if [ ! -f "${SRC}/image/setup.sh" ]; then
  echo "kid-tv source not found (looked in ${HERE}/files/kidtv-src and ${HERE}/../../..)" >&2
  exit 1
fi
echo "kid-tv: installing from ${SRC}"
install -d "${ROOTFS_DIR}/opt/kidtv-src"
rsync -a --delete --exclude '.git' --exclude 'pi-gen' --exclude 'deploy' --exclude 'work' \
  --exclude 'image/stage-kidtv/00-install/files' \
  "${SRC}/" "${ROOTFS_DIR}/opt/kidtv-src/"
on_chroot <<CHROOT
export KIDTV_SRC=/opt/kidtv-src KIDTV_SKIP_APT=1 KIDTV_IN_CHROOT=1
bash /opt/kidtv-src/image/setup.sh
rm -rf /opt/kidtv-src
CHROOT
