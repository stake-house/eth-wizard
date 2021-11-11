import os
import sys
import json

import logging

from pathlib import Path

from typing import Optional

from ethwizard import __version__

from ethwizard.constants import (
    STATE_FILE
)

log = logging.getLogger(__name__)

def save_state(step_id: str, context: dict) -> bool:
    # Save wizard state

    data_to_save = {
        'step': step_id,
        'context': context
    }

    app_data = Path(os.getenv('LOCALAPPDATA', os.getenv('APPDATA', '')))
    if not app_data.is_dir():
        return False
    
    app_dir = app_data.joinpath('eth-wizard')
    app_dir.mkdir(parents=True, exist_ok=True)
    save_file = app_dir.joinpath(STATE_FILE)

    with open(str(save_file), 'w', encoding='utf8') as output_file:
        json.dump(data_to_save, output_file)

    return True

def load_state() -> Optional[dict]:
    # Load wizard state

    app_data = Path(os.getenv('LOCALAPPDATA', os.getenv('APPDATA', '')))
    if not app_data.is_dir():
        return None
    
    app_dir = app_data.joinpath('eth-wizard')
    if not app_dir.is_dir():
        return None
    
    save_file = app_dir.joinpath(STATE_FILE)
    if not save_file.is_file():
        return None
    
    loaded_data = None

    try:
        with open(str(save_file), 'r', encoding='utf8') as input_file:
            loaded_data = json.load(input_file)
    except ValueError:
        return None
    
    return loaded_data

def quit_app():
    print('Press enter to quit')
    input()
    
    log.info(f'Quitting eth-wizard')
    sys.exit()

def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    log.critical('Uncaught exception', exc_info=(exc_type, exc_value, exc_traceback))

def init_logging():
    # Initialize logging
    log.setLevel(logging.INFO)

    # Handle uncaught exception and log them
    sys.excepthook = handle_exception

    # Console handler to log into the console
    ch = logging.StreamHandler()
    log.addHandler(ch)

    # File handler to log into a file
    app_data = Path(os.getenv('LOCALAPPDATA', os.getenv('APPDATA', '')))
    if app_data.is_dir():
        app_dir = app_data.joinpath('eth-wizard')
        app_dir.mkdir(parents=True, exist_ok=True)
        log_file = app_dir.joinpath('app.log')
        fh = logging.FileHandler(log_file, encoding='utf8')

        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)

        log.addHandler(fh)

    log.info(f'Starting eth-wizard version {__version__}')