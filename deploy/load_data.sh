#!/bin/sh
# Load your carried-over data into the stack's Docker volumes.
#
# Run this ON THE PORTAINER PC, after the stack has been deployed once
# (so the volumes exist). Unzip marksvision-data-bundle.zip first, then run
# this script from inside the unzipped folder.
#
# Usage:   sh load_data.sh [stack-name]        (default stack name: marksvision)
#
# IMPORTANT: stop the stack in Portainer first (so nothing is writing to the
# database), run this, then start the stack again.

set -e
STACK="${1:-marksvision}"
SRC="$(pwd)"

echo "Loading data into volumes of stack '$STACK' ..."

# database
docker run --rm -v "${STACK}_mvc_db:/dst" -v "$SRC:/src" alpine \
  sh -c "cp /src/db.sqlite3 /dst/db.sqlite3 && echo '  db.sqlite3 -> mvc_db'"

# uploaded media (profile pictures, generated reports)
if [ -d "$SRC/media" ]; then
  docker run --rm -v "${STACK}_mvc_media:/dst" -v "$SRC/media:/src" alpine \
    sh -c "cp -r /src/. /dst/ && echo '  media/ -> mvc_media'"
fi

# trained ML models
if [ -d "$SRC/ml_artifacts" ]; then
  docker run --rm -v "${STACK}_mvc_ml:/dst" -v "$SRC/ml_artifacts:/src" alpine \
    sh -c "cp -r /src/. /dst/ && echo '  ml_artifacts/ -> mvc_ml'"
fi

echo "Done. Start the stack again in Portainer."
