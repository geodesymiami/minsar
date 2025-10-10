#!/usr/bin/env bash
######### copy credentials to right place ##############

# Determine the script's directory
SCRIPT_DIR=$(dirname "$(realpath "${BASH_SOURCE[0]}")")
echo SCRIPT_DIR "$SCRIPT_DIR"

# for ssara
SSARA_FILE="$SCRIPT_DIR/../tools/ssara_client/password_config.py"
characterCount=$(wc -m < "$SSARA_FILE" | xargs)

if [[ $characterCount == 141 ]]; then
  echo "Copying ~/accounts/password_config.py into $SCRIPT_DIR/../tools/ssara_client"
  cp ~/accounts/password_config.py "$SCRIPT_DIR/../tools/ssara_client"
else
  echo "SSARA password_config.py has contents - kept unchanged"
fi

# for dem.py
if [[ ! -f ~/.netrc ]]; then
  echo "copying .netrc file for DEM data download into ~/.netrc"
  cp ~/accounts/netrc ~/.netrc
fi

# for pyaps
if [[ ! -f ~/.cdsapirc ]]; then
  echo "Copying default cdsapirc for ECMWF download with PyAPS into HOME directory"
  cp ~/accounts/cdsapirc ~/.cdsapirc
else
  echo "File  ~/.cdsapirc exists already - kept unchanged"
fi
