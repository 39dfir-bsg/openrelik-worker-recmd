# Openrelik worker RECmd
## Description
This worker runs eric zimmerman's RECmd application against a filetree consistent archives (like KAPE image .zip files) holding registry hives, using the DFIR Batch files.

This is required as RECmd uses filenames and file paths to match transaction logs, which is incompatible with how OpenRelik renames input files.

This is not the optimal solution, but it works!

For more info on DFIR Batch files https://github.com/EricZimmerman/RECmd/blob/master/BatchExamples/DFIRBatch.md

Supports `.openrelik-hostname` files provided as part of a `openrelik-config.zip`.

Supply a `.openrelik-hostname` file in an `openrelik-config.zip` archive to this worker and it will prefix any output with the included hostname.

## Deploy
Update your `config.env` file to set `OPENRELIK_WORKER_RECMD_VERSION` to the tagged release version you want to use.

Add the below configuration to the OpenRelik docker-compose.yml file, you may need to update the `image:` value to point to the container in a  registry.

```
openrelik-worker-remd:
    container_name: openrelik-worker-recmd
    image: openrelik-worker-recmd:${OPENRELIK_WORKER_RECMD_VERSION}
    restart: always
    environment:
      - REDIS_URL=redis://openrelik-redis:6379
    volumes:
      - ./data:/usr/share/openrelik/data
    command: "celery --app=src.app worker --task-events --concurrency=4 --loglevel=INFO -Q openrelik-worker-recmd"
    
    # ports:
      # - 5678:5678 # For debugging purposes.
```
