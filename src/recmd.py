import os
import shutil
import subprocess
import time
from uuid import uuid4
from pathlib import Path

from celery import signals
from celery.utils.log import get_task_logger

from openrelik_common.logging import Logger
from openrelik_worker_common.archive_utils import extract_archive
from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from pathvalidate import sanitize_filename

from .app import celery

# Task name used to register and route the task to the correct queue.
TASK_NAME = "openrelik-worker-recmd.tasks.recmd"

# Task metadata for registration in the core system.
TASK_METADATA = {
    "display_name": "Eric Zimmerman's RECmd tool",
    "description": "Runs Eric Zimmerman's RECmd application on Registry Hives in filetree consistent archives (like KAPE .zip images) using the DFIR Batch files",
    "task_config": [
        {
            "name": "archive_password",
            "label": "Password for the input archives",
            "description": "The password needed to extract the input archives",
            "type": "text",
            "required": False,
        },
    ],
}

log_root = Logger()
logger = log_root.get_logger(__name__, get_task_logger(__name__))


@signals.task_prerun.connect
def on_task_prerun(sender, task_id, task, args, kwargs, **_):
    log_root.bind(
        task_id=task_id,
        task_name=task.name,
        worker_name=TASK_METADATA.get("display_name"),
    )

@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def recmd(
    self,
    pipe_result=None,
    input_files=[],
    output_path=None,
    workflow_id=None,
    task_config={},
) -> str:

    log_root.bind(workflow_id=workflow_id)
    logger.info(f"Starting {TASK_NAME} for workflow {workflow_id}")

    output_files = []
    input_files = get_input_files(pipe_result, input_files or [])
    task_files = []
    command_string = ""
    archive_password = task_config.get("archive_password", None)
    if not input_files:
        return create_task_result(
            output_files=output_files,
            workflow_id=workflow_id,
            command="",
        )

    # Support openrelik-config.zip -> .openrelik-hostname
    prefix = ""
    # Extract openrelik-config.zip
    if (config_item := next((f for f in input_files if f.get('display_name') == "openrelik-config.zip"), None)):
        log_file = create_output_file(
            output_path,
            display_name=f"extract_archives_{config_item.get('display_name')}.log",
        )
        try:
            (command_string, export_directory) = extract_archive(
                config_item, output_path, log_file.path, ["*.openrelik-hostname"], archive_password
            )
        except Exception as e:
            logger.error(f"extract_archive on openrelik-config.zip failed: {e}")
            raise
        
        logger.info(f"Executed extract_archive command: {command_string}")

        if os.path.isfile(log_file.path):
            task_files.append(log_file.to_dict())

        export_directory_path = Path(export_directory)
        extracted_files = [
            file for file in export_directory_path.glob("**/*") if file.is_file()
        ]
        if (hostname_item := next((f for f in extracted_files if f.name == ".openrelik-hostname"), None)):
            with open(hostname_item.absolute(),"r", encoding="utf-8") as f:
                raw_hostname = f.read().strip()
            prefix = f"{sanitize_filename(raw_hostname)}_"
        else:
            logger.info(f"No .openrelik-hostname file found in openrelik-config.zip")
        # clean up export directory
        shutil.rmtree(export_directory)

    # Extract zip images and run RECmd
    non_config_files = [f for f in input_files if f.get('display_name') != "openrelik-config.zip"]
    if len(non_config_files) != 1:
        logger.error(f"more than one zip file provided to extract (ignoring any openrelik-config.zip files)")
        raise ValueError("Expected exactly one non-config ZIP file to extract")
    
    for input_file in non_config_files:
        log_root.bind(input_file=input_file)
        logger.info(f"Processing {input_file}")

        log_file = create_output_file(
            output_path,
            display_name=f"extract_archives_{input_file.get('display_name')}.log",
        )

        try:
            (command_string, export_directory) = extract_archive(
                input_file, output_path, log_file.path, [], archive_password
            )
        except Exception as e:
            logger.error(f"extract_archive failed: {e}")
            raise
        
        logger.info(f"Executed extract_archive command: {command_string}")

        if os.path.isfile(log_file.path):
            task_files.append(log_file.to_dict())

        export_directory_path = Path(export_directory).as_posix()

        output_file = create_output_file(
            output_path,
            display_name=f"{prefix}RECmd_output.csv",
            data_type="openrelik:recmd:recmd",
        )

        # -d %sourceDirectory% --bn BatchExamples\DFIRBatch.reb --nl false --csv %destinationDirectory%
        command = [
            "dotnet",
            "/recmd/RECmd/RECmd.dll",
            "-d",
            export_directory_path,
            "--bn",
            "/recmd/RECmd/BatchExamples/DFIRBatch.reb",
            "--nl",
            "false",
            "--csv",
            output_path,
            "--csvf",
            output_file.path,
        ]

        INTERVAL_SECONDS = 2
        process = subprocess.Popen(command)
        while process.poll() is None:
            self.send_event("task-progress", data=None)
            time.sleep(INTERVAL_SECONDS)

        output_files.append(output_file.to_dict())

        # Clean up the export directory
        shutil.rmtree(export_directory)

    return create_task_result(
        output_files=output_files,
        workflow_id=workflow_id,
        command=" ".join(command),
    )
