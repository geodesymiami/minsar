#!/usr/bin/env bash
######### copy credentials to right place ##############

# for ssara
SSARA_FILE=tools/ssara_client/password_config.py
characterCount=$(wc -m < "$SSARA_FILE" | xargs)

if [[ $characterCount == 290 ]]; then
  echo "This looks like a virgin file from a new git clone:  tools/ssara_client/password_config.py"
  echo "Copying from ~/accounts into tools/ssara_client"
  cp ~/accounts/password_config.py tools/ssara_client
else
  echo "tools/ssara_client/password_config.py contains credentials -- kept unchanged"
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
