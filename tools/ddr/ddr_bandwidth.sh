#!/bin/sh

PROGRAM=${0##*/}
DEFAULT_SOC_DIR=/sys/devices/platform/soc

CAPTURE_PERIOD=100
DDR_FREQUENCY=3200
DDR_BIT_WIDTH=32
CAPTURE_SIZE=0x100000
CAPTURE_TIME=30
CAPTURE_ADDRESS=0xf0000000
DDRC_COUNT=1
MEASUREMENT_COUNT=

usage()
{
    cat <<EOF
Usage: $PROGRAM [-p period] [-f frequency] [-w width] [-b size] [-t seconds] [-d address] [-c count] [-n count]

Continuously monitor VS859 DDR bandwidth with the perfstat driver.
Bandwidth is displayed in decimal MB/s.

Options:
  -p PERIOD    Capture period in us            (default: 100)
  -f FREQ      DDR controller frequency in MHz (default: 3200)
  -w WIDTH     Legacy driver bus width: 16/32  (default: 32)
  -b SIZE      Capture buffer size in bytes    (default: 0x100000)
  -t SECONDS   Duration of each sample         (default: 30)
  -d ADDRESS   Free DDR buffer address         (default: 0xf0000000)
  -c COUNT     Number of DDR controllers       (default: 1)
  -n COUNT     Stop after COUNT samples        (default: continuous)
  -h           Show this help

Example:
  $PROGRAM -p 100 -f 3733 -w 32 -b 0x100000 -t 1 -d 0xf0000000 -c 2 -n 1

Press Ctrl+C to stop continuous monitoring.
EOF
}

die()
{
    echo "$PROGRAM: $*" >&2
    echo "Try '$PROGRAM -h' for usage." >&2
    exit 1
}

is_positive_decimal()
{
    case $1 in
        ''|*[!0-9]*|0) return 1 ;;
        *) return 0 ;;
    esac
}

is_uint()
{
    case $1 in
        '')
            return 1
            ;;
        0x*|0X*)
            digits=${1#??}
            case $digits in
                ''|*[!0-9a-fA-F]*) return 1 ;;
                *) return 0 ;;
            esac
            ;;
        *[!0-9]*)
            return 1
            ;;
        *)
            return 0
            ;;
    esac
}

while getopts ':hp:f:w:b:t:d:c:n:' option; do
    case $option in
        h)
            usage
            exit 0
            ;;
        p) CAPTURE_PERIOD=$OPTARG ;;
        f) DDR_FREQUENCY=$OPTARG ;;
        w) DDR_BIT_WIDTH=$OPTARG ;;
        b) CAPTURE_SIZE=$OPTARG ;;
        t) CAPTURE_TIME=$OPTARG ;;
        d) CAPTURE_ADDRESS=$OPTARG ;;
        c) DDRC_COUNT=$OPTARG ;;
        n) MEASUREMENT_COUNT=$OPTARG ;;
        :) die "option -$OPTARG requires a value" ;;
        \?) die "unknown option: -$OPTARG" ;;
    esac
done
shift $((OPTIND - 1))

[ "$#" -eq 0 ] || die "unexpected argument: $1"
is_positive_decimal "$CAPTURE_PERIOD" ||
    die "capture period must be a positive decimal integer"
is_positive_decimal "$DDR_FREQUENCY" ||
    die "DDR frequency must be a positive decimal integer"
case $DDR_BIT_WIDTH in
    16|32) ;;
    *) die "DDR bus width must be 16 or 32" ;;
esac
is_uint "$CAPTURE_SIZE" ||
    die "capture buffer size must be decimal or hexadecimal"
is_positive_decimal "$CAPTURE_TIME" ||
    die "capture duration must be a positive decimal integer"
is_positive_decimal "$DDRC_COUNT" ||
    die "DDRC count must be a positive decimal integer"
if [ -n "$MEASUREMENT_COUNT" ]; then
    is_positive_decimal "$MEASUREMENT_COUNT" ||
        die "measurement count must be a positive decimal integer"
fi
is_uint "$CAPTURE_ADDRESS" ||
    die "capture buffer address must be decimal or hexadecimal"

if [ -z "${PERFSTAT_DIR:-}" ]; then
    PERFSTAT_SOC_DIR=${PERFSTAT_SOC_DIR:-$DEFAULT_SOC_DIR}
    set -- "$PERFSTAT_SOC_DIR"/*.perfstat
    if [ "$#" -ne 1 ] || [ ! -d "$1" ]; then
        if [ "$#" -gt 1 ]; then
            die "multiple perfstat devices found under $PERFSTAT_SOC_DIR; set PERFSTAT_DIR explicitly"
        fi
        die "no perfstat device found under $PERFSTAT_SOC_DIR"
    fi
    PERFSTAT_DIR=$1
fi

case $PERFSTAT_DIR in
    /sys/*)
        [ "$(id -u)" -eq 0 ] || die "root privileges are required"
        ;;
esac

if [ ! -d "$PERFSTAT_DIR" ]; then
    die "perfstat directory not found: $PERFSTAT_DIR"
fi
for node in period ddrfrq size addr start stop; do
    node_path=$PERFSTAT_DIR/perfstat_$node
    [ -e "$node_path" ] || die "perfstat node not found: $node_path"
    [ -w "$node_path" ] || die "perfstat node is not writable: $node_path"
done
BIT_WIDTH_NODE=$PERFSTAT_DIR/perfstat_bitwide
if [ -e "$BIT_WIDTH_NODE" ] && [ ! -w "$BIT_WIDTH_NODE" ]; then
    die "perfstat node is not writable: $BIT_WIDTH_NODE"
fi
RESULT_NODE=$PERFSTAT_DIR/perfstat_show
[ -e "$RESULT_NODE" ] || die "perfstat node not found: $RESULT_NODE"
[ -r "$RESULT_NODE" ] || die "perfstat node is not readable: $RESULT_NODE"
command -v awk > /dev/null 2>&1 || die "awk is required for MB/s conversion"

write_node()
{
    value=$1
    path=$2
    if ! printf '%s\n' "$value" > "$path"; then
        die "failed to write $path"
    fi
}

print_result()
{
    if ! awk -v ddrc_count="$DDRC_COUNT" '
        {
            if (match($0, /[0-9][0-9]*\.[0-9][0-9]* Gbps/)) {
                bandwidth = substr($0, RSTART, RLENGTH)
                sub(/ Gbps$/, "", bandwidth)
                converted = sprintf("%.3f MB/s", bandwidth * 125 * ddrc_count)
                $0 = substr($0, 1, RSTART - 1) converted \
                    substr($0, RSTART + RLENGTH)
            } else if (match($0, /[0-9][0-9]*\.[0-9][0-9]* MB\/s/)) {
                bandwidth = substr($0, RSTART, RLENGTH)
                sub(/ MB\/s$/, "", bandwidth)
                converted = sprintf("%.3f MB/s", bandwidth * ddrc_count)
                $0 = substr($0, 1, RSTART - 1) converted \
                    substr($0, RSTART + RLENGTH)
            }
            print
        }
    ' "$RESULT_NODE"; then
        die "failed to convert perfstat result to MB/s"
    fi
}

CAPTURE_ACTIVE=0
SLEEP_PID=

stop_capture()
{
    if [ "$CAPTURE_ACTIVE" -eq 1 ]; then
        if ! printf '%s\n' 1 > "$PERFSTAT_DIR/perfstat_stop"; then
            echo "$PROGRAM: failed to stop perfstat capture" >&2
            return 1
        fi
        CAPTURE_ACTIVE=0
    fi
}

handle_signal()
{
    exit_status=$1
    signal_name=$2
    trap - HUP INT TERM
    if [ -n "$SLEEP_PID" ]; then
        kill "$SLEEP_PID" 2>/dev/null
        wait "$SLEEP_PID" 2>/dev/null
        SLEEP_PID=
    fi
    stop_capture
    echo "$PROGRAM: interrupted by $signal_name" >&2
    exit "$exit_status"
}

trap 'handle_signal 129 HUP' HUP
trap 'handle_signal 130 INT' INT
trap 'handle_signal 143 TERM' TERM

write_node "$CAPTURE_PERIOD" "$PERFSTAT_DIR/perfstat_period"
write_node "$DDR_FREQUENCY" "$PERFSTAT_DIR/perfstat_ddrfrq"
if [ -e "$BIT_WIDTH_NODE" ]; then
    write_node "$DDR_BIT_WIDTH" "$BIT_WIDTH_NODE"
fi
write_node "$CAPTURE_SIZE" "$PERFSTAT_DIR/perfstat_size"
write_node "$CAPTURE_ADDRESS" "$PERFSTAT_DIR/perfstat_addr"

SLEEP_COMMAND=${PERFSTAT_SLEEP_CMD:-sleep}
sample_number=1
while :; do
    write_node 1 "$PERFSTAT_DIR/perfstat_start"
    CAPTURE_ACTIVE=1

    "$SLEEP_COMMAND" "$CAPTURE_TIME" &
    SLEEP_PID=$!
    if wait "$SLEEP_PID"; then
        sleep_status=0
    else
        sleep_status=$?
    fi
    SLEEP_PID=

    if [ "$sleep_status" -ne 0 ]; then
        stop_capture
        die "capture wait failed with status $sleep_status"
    fi

    stop_capture || exit 1
    printf '\n[%s] Sample %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" \
        "$sample_number"
    print_result

    if [ -n "$MEASUREMENT_COUNT" ] && \
        [ "$sample_number" -ge "$MEASUREMENT_COUNT" ]; then
        break
    fi
    sample_number=$((sample_number + 1))
done

trap - HUP INT TERM
