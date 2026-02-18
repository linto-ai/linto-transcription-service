#!/bin/bash
set -e
echo "RUNNING : Transcription request service"

# Set default UID and GID (defaults to www-data: 33:33 if not specified)
USER_ID=${USER_ID:-33}
GROUP_ID=${GROUP_ID:-33}

# Default values for user and group names
USER_NAME="appuser"
GROUP_NAME="appgroup"

# Function to create a user/group if needed and adjust permissions
function setup_user() {
    echo "Configuring runtime user with UID=$USER_ID and GID=$GROUP_ID"

    # Check if a group with the specified GID already exists
    if getent group "$GROUP_ID" >/dev/null 2>&1; then
        GROUP_NAME=$(getent group "$GROUP_ID" | cut -d: -f1)
        echo "A group with GID=$GROUP_ID already exists: $GROUP_NAME"
    else
        # Create the group if it does not exist
        echo "Creating group with GID=$GROUP_ID"
        groupadd -g "$GROUP_ID" "$GROUP_NAME"
    fi

    # Check if a user with the specified UID already exists
    if getent passwd "$USER_ID" >/dev/null 2>&1; then
        USER_NAME=$(getent passwd "$USER_ID" | cut -d: -f1)
        echo "A user with UID=$USER_ID already exists: $USER_NAME"
    else
        # Create the user if it does not exist
        echo "Creating user with UID=$USER_ID and GID=$GROUP_ID"
        useradd -m -u "$USER_ID" -g "$GROUP_NAME" "$USER_NAME"
    fi

    # Adjust ownership of the application directories
    echo "Adjusting ownership of application directories"
    chown -R "$USER_NAME:$GROUP_NAME" /usr/src/app
}

# Setup the runtime user
setup_user

./wait-for-it.sh $(echo $SERVICES_BROKER | cut -d'/' -f 3) --timeout=20 --strict -- echo " $REDIS_BROKER (Service Broker) is up"
./wait-for-it.sh $MONGO_HOST:$MONGO_PORT --timeout=20 --strict -- echo " $MONGO_HOST:$MONGO_PORT  (MONGO DB) is up"

export USER_NAME="$USER_NAME"
supervisord -c supervisor/supervisor.conf
supervisorctl -c supervisor/supervisor.conf tail -f ingress stderr
