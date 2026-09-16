#!/bin/bash -e
# Copy the repository into the image and run the shared provisioning script.
install -d "${ROOTFS_DIR}/opt/kidtv-src"
rsync -a --delete --exclude '.git' --exclude 'pi-gen' --exclude 'deploy' --exclude 'work' \
  "${STAGE_DIR}/../../" "${ROOTFS_DIR}/opt/kidtv-src/"
on_chroot <<CHROOT
export KIDTV_SRC=/opt/kidtv-src KIDTV_SKIP_APT=1 KIDTV_IN_CHROOT=1
bash /opt/kidtv-src/image/setup.sh
rm -rf /opt/kidtv-src
CHROOT
