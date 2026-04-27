#!/usr/bin/env bash
#
# Test suite for minsarApp.bash option-resolution behavior.
#

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
MINSAR_APP="$PROJECT_ROOT/minsar/bin/minsarApp.bash"

source "$SCRIPT_DIR/test_helpers.bash"

make_mock_command() {
    local mock_bin="$1"
    local cmd_name="$2"
    cat > "$mock_bin/$cmd_name" << 'EOF'
#!/usr/bin/env bash
echo "MOCK_CMD:$(basename "$0") $*" >> "${MINSAR_TEST_CMD_LOG:-/tmp/minsar_test_cmd.log}"
exit 0
EOF
    chmod +x "$mock_bin/$cmd_name"
}

setup_minsar_app_test_env() {
    setup_test_workspace

    TEST_TMP="$TEST_WORKSPACE/minsarapp"
    mkdir -p "$TEST_TMP/templates" "$TEST_TMP/mockbin" "$TEST_TMP/scratch" "$TEST_TMP/samples"

    # Template-dependent directories used by minsarApp internals.
    mkdir -p "$TEST_TMP/scratch/testproj/reference" "$TEST_TMP/scratch/testproj/merged/SLC/20200101" "$TEST_TMP/scratch/testproj/merged/SLC/20200201"
    touch "$TEST_TMP/scratch/testproj/reference/IW1.xml"

    export MINSAR_HOME="$PROJECT_ROOT"
    export SCRATCHDIR="$TEST_TMP/scratch"
    export TEMPLATES="$TEST_TMP/templates"
    export SAMPLESDIR="$TEST_TMP/samples"
    export JOBSHEDULER_PROJECTNAME="A-TEST"
    export QUEUENAME="normal"
    export PLATFORM_NAME="stampede3"
    export ISCE_STACK="$TEST_TMP/isce_stack"
    export MINSAR_TEST_CMD_LOG="$TEST_TMP/cmd.log"
    : > "$MINSAR_TEST_CMD_LOG"

    # Mock command used by get_reference_date().
    cat > "$TEST_TMP/mockbin/xmllint" << 'EOF'
#!/usr/bin/env bash
echo "2020-01-01 00:00:00"
exit 0
EOF
    chmod +x "$TEST_TMP/mockbin/xmllint"

    # Mock all external commands that minsarApp may invoke in these tests.
    for cmd in \
        run_workflow.bash run_clean_dir.bash run_download_orbits_asf.bash \
        create_runfiles.py create_jobfile_to_generate_miaplpy_jobfiles.py \
        create_save_hdfeos5_jobfile.py create_html.py \
        summarize_resource_usage.py generate_download_command.py remove_problem_data.py \
        add_missing_attributes.py flip_sign_bperp.py \
        generate_makedem_command.py makedem_sardem.sh make_zero_elevation_dem.py \
        unpack_SLCs.py pack_bursts.sh cmd2jobfile.py download_burst2safe.sh \
        download_burst2stack.sh download_slc.sh create_ingest_insarmaps_jobfile.py; do
        make_mock_command "$TEST_TMP/mockbin" "$cmd"
    done

    cat > "$TEST_TMP/mockbin/upload_data_products.py" << 'EOF'
#!/usr/bin/env bash
echo "MOCK_CMD:$(basename "$0") $*" >> "${MINSAR_TEST_CMD_LOG:-/tmp/minsar_test_cmd.log}"
echo "http://new-upload-url" >> upload.log
exit 0
EOF
    chmod +x "$TEST_TMP/mockbin/upload_data_products.py"

    cat > "$TEST_TMP/mockbin/create_ingest_insarmaps_jobfile.py" << 'EOF'
#!/usr/bin/env bash
echo "MOCK_CMD:$(basename "$0") $*" >> "${MINSAR_TEST_CMD_LOG:-/tmp/minsar_test_cmd.log}"
touch ingest_insar_mock.job
echo "http://new-insarmaps-url" >> insarmaps.log
exit 0
EOF
    chmod +x "$TEST_TMP/mockbin/create_ingest_insarmaps_jobfile.py"

    export PATH="$TEST_TMP/mockbin:$PATH"
}

write_template() {
    local path="$1"
    local coreg="$2"
    local workflow="${3:-interferogram}"
    cat > "$path" << EOF
ssaraopt.platform               = SENTINEL-1A,SENTINEL-1B
topsStack.coregistration        = $coreg
topsStack.workflow              = $workflow
minsar.upload_flag              = False
minsar.insarmaps_flag           = False
minsar.upload_option            = None
EOF
}

run_minsar_app() {
    local template_file="$1"
    shift
    (
        cd "$PROJECT_ROOT" || exit 1
        bash "$MINSAR_APP" "$template_file" "$@"
    ) 2>&1
}

test_isce_start_implies_ifgram_and_geometry_stop_8() {
    print_test_start "ISCE start implies ifgram (geometry)" \
        "Verifies --isce-start without --start auto-runs ifgram and defaults to stop=8 for geometry."
    setup_minsar_app_test_env

    local tpl="$TEMPLATES/testproj.template"
    write_template "$tpl" "geometry"
    local output
    output="$(run_minsar_app "$tpl" --no-mintpy --miaplpy --isce-start 6)"

    assert_contains "$output" "Running.... run_workflow.bash --start 6 --stop 8" \
        "Geometry defaults to stop=8 when --isce-start is provided without --isce-stop"
    assert_not_contains "$output" "run_download_orbits_asf.bash" \
        "Orbit download is skipped when inferred start is ifgram"

    teardown_test_workspace
    print_test_end "ISCE start implies ifgram (geometry)"
}

test_isce_start_defaults_to_stop_12_for_nesd_auto() {
    print_test_start "ISCE stop defaults (NESD/auto)" \
        "Verifies --isce-start without --isce-stop defaults to stop=12 for non-geometry coregistration."
    setup_minsar_app_test_env

    local tpl="$TEMPLATES/testproj.template"
    write_template "$tpl" "auto"
    local output
    output="$(run_minsar_app "$tpl" --isce-start 6)"

    assert_contains "$output" "Running.... run_workflow.bash --start 6 --stop 12" \
        "NESD/auto defaults to stop=12 when --isce-start is provided without --isce-stop"
    assert_not_contains "$output" "run_download_orbits_asf.bash" \
        "Orbit download is skipped when inferred start is ifgram"

    teardown_test_workspace
    print_test_end "ISCE stop defaults (NESD/auto)"
}

test_miaplpy_start_without_start_disables_orbit_download() {
    print_test_start "MiaplPy start normalization" \
        "Verifies --miaplpy-start works without --start miaplpy and does not trigger orbit download."
    setup_minsar_app_test_env

    local tpl="$TEMPLATES/testproj.template"
    write_template "$tpl" "auto"
    local output
    output="$(run_minsar_app "$tpl" --miaplpy-start 6 --miaplpy-stop 7 --skip-miaplpy)"

    assert_contains "$output" "Running.... create_save_hdfeos5_jobfile.py" \
        "MiaplPy pipeline is selected even without explicit --start miaplpy"
    assert_not_contains "$output" "run_download_orbits_asf.bash" \
        "Orbit download is skipped when starting at miaplpy"

    teardown_test_workspace
    print_test_end "MiaplPy start normalization"
}

test_geometry_does_not_disable_mintpy() {
    print_test_start "Geometry does not disable MintPy" \
        "Verifies mintpy_flag stays 1 for geometry (coregistration no longer overrides mintpy)."
    setup_minsar_app_test_env

    local tpl="$TEMPLATES/testproj.template"
    write_template "$tpl" "geometry"
    local output
    output="$(run_minsar_app "$tpl" --start jobfiles --skip-mintpy --skip-miaplpy)"

    assert_contains "$output" "Flags for processing steps:" \
        "minsarApp prints final resolved processing flags"
    assert_contains "$output" "jobfiles ifgram mintpy miaplpy upload insarmaps opposite_orbit horzvert" \
        "Flag header is present"
    assert_contains "$output" "0        0       0      1       1       1" \
        "Resolved flags show mintpy enabled for geometry (workflow not slc, no --isce-stop)"

    teardown_test_workspace
    print_test_end "Geometry does not disable MintPy"
}

test_slc_workflow_disables_mintpy() {
    print_test_start "slc workflow disables MintPy" \
        "Verifies mintpy_flag is 0 when topsStack.workflow is slc."
    setup_minsar_app_test_env

    local tpl="$TEMPLATES/testproj.template"
    write_template "$tpl" "NESD" "slc"
    local output
    output="$(run_minsar_app "$tpl" --start jobfiles --skip-mintpy --skip-miaplpy)"

    assert_contains "$output" "0        0       0      1       1       0" \
        "Resolved flags show mintpy disabled for slc workflow"

    teardown_test_workspace
    print_test_end "slc workflow disables MintPy"
}

test_isce_stop_on_cli_disables_mintpy() {
    print_test_start "--isce-stop on CLI disables MintPy" \
        "Verifies mintpy_flag is 0 when user provides --isce-stop."
    setup_minsar_app_test_env

    local tpl="$TEMPLATES/testproj.template"
    write_template "$tpl" "NESD"
    local output
    output="$(run_minsar_app "$tpl" --start jobfiles --isce-stop 8 --skip-mintpy --skip-miaplpy)"

    assert_contains "$output" "0        0       0      1       1       0" \
        "Resolved flags show mintpy disabled when --isce-stop is given"

    teardown_test_workspace
    print_test_end "--isce-stop on CLI disables MintPy"
}

test_inconsistent_start_and_miaplpy_start_exits() {
    print_test_start "Inconsistent options validation" \
        "Verifies --start jobfiles with --miaplpy-start exits with clear error."
    setup_minsar_app_test_env

    local tpl="$TEMPLATES/testproj.template"
    write_template "$tpl" "auto"
    local output
    set +e
    output="$(run_minsar_app "$tpl" --start jobfiles --miaplpy-start 6)"
    local exit_code=$?
    set -e

    assert_exit_code 1 "$exit_code" \
        "minsarApp exits non-zero for inconsistent --start and --miaplpy-start"
    assert_contains "$output" "USER ERROR: Inconsistent options: --miaplpy-start requires --start miaplpy (or omit --start)." \
        "Error message explains invalid option combination"

    teardown_test_workspace
    print_test_end "Inconsistent options validation"
}

test_summary_prints_only_current_run_urls() {
    print_test_start "Summary uses current-run log deltas" \
        "Verifies footer prints only upload/insarmaps URLs added in the current run."
    setup_minsar_app_test_env

    local tpl="$TEMPLATES/testproj.template"
    write_template "$tpl" "auto"

    # Pre-existing log entries from prior runs should not appear in summary.
    echo "http://old-upload-url" > "$SCRATCHDIR/testproj/upload.log"
    echo "http://old-insarmaps-url" > "$SCRATCHDIR/testproj/insarmaps.log"

    local output
    output="$(run_minsar_app "$tpl" --start miaplpy --no-mintpy --miaplpy --skip-miaplpy --upload --insarmaps)"

    assert_contains "$output" "Data products uploaded to:" \
        "Summary header is printed when current run produced upload/ingest URLs"
    assert_contains "$output" "http://new-upload-url" \
        "Summary includes upload URL from current run"
    assert_contains "$output" "http://new-insarmaps-url" \
        "Summary includes insarmaps URL from current run"
    assert_not_contains "$output" "http://old-upload-url" \
        "Summary excludes upload URL from previous runs"
    assert_not_contains "$output" "http://old-insarmaps-url" \
        "Summary excludes insarmaps URL from previous runs"

    local cmd_log
    cmd_log="$(<"$MINSAR_TEST_CMD_LOG")"
    assert_contains "$cmd_log" "upload_data_products.py" \
        "Upload command is executed"
    assert_contains "$cmd_log" "--quiet-summary" \
        "minsarApp passes --quiet-summary to child upload/ingest workflows"

    teardown_test_workspace
    print_test_end "Summary uses current-run log deltas"
}

print_header "MINSARAPP OPTION RESOLUTION TEST SUITE"

test_isce_start_implies_ifgram_and_geometry_stop_8
test_isce_start_defaults_to_stop_12_for_nesd_auto
test_miaplpy_start_without_start_disables_orbit_download
test_geometry_does_not_disable_mintpy
test_slc_workflow_disables_mintpy
test_isce_stop_on_cli_disables_mintpy
test_inconsistent_start_and_miaplpy_start_exits
test_summary_prints_only_current_run_urls

print_summary
exit $?
