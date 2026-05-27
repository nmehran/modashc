#!/bin/bash

MAKEPKG_LIBRARY=${MAKEPKG_LIBRARY:-./scripts/libmakepkg}

source "$MAKEPKG_LIBRARY/util/util.sh"
source_safe ./source-safe-target.sh
echo "wrapper:$MODASHC_REALWORLD_SOURCE_SAFE"
