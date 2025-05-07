#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Log file for debugging
LOG_FILE="$DIR/update.log"

log() {
	echo "$(date): $1" >> "$LOG_FILE"
	echo "$1"
}

log "Update script started"
log "Working directory: $DIR"

sleep 2

if [ -f "$DIR/run.py" ]; then
	RUN_SCRIPT="$DIR/run.py"
	log "Found run.py in: $DIR"
elif [ -f "$DIR/aeda-node/run.py" ]; then
	RUN_SCRIPT="$DIR/aeda-node/run.py"
	log "Found run.py in: $DIR/aeda-node"
else
	FOUND_SCRIPT=$(find "$DIR" -name "run.py" -type f | head -n 1)
	if [ -n "$FOUND_SCRIPT" ]; then
		RUN_SCRIPT="$FOUND_SCRIPT"
		log "Found run.py at: $FOUND_SCRIPT"
	else
		log "Could not find run.py!"
		exit 1
	fi
fi

RUN_DIR=$(dirname "$RUN_SCRIPT")
log "Run script directory: $RUN_DIR"

PID=$(pgrep -f "python run.py")
if [ ! -z "$PID" ]; then
	log "Killing current process with PID: $PID"
	kill $PID
	sleep 2
fi

NODE_ARGS_FILE="$RUN_DIR/.node_args"
if [ -f "$NODE_ARGS_FILE" ]; then
	NODE_ARGS=$(cat "$NODE_ARGS_FILE")
	log "Using node arguments: $NODE_ARGS"
else
	NODE_ARGS=""
	log "No node arguments found"
fi

cd "$RUN_DIR" || { log "Failed to change to run directory"; exit 1; }

log "Restarting application from $RUN_DIR..."
python run.py $NODE_ARGS >> "$LOG_FILE" 2>&1 &

log "Update script completed"

exit 0
