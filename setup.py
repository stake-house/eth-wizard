import setuptools
import os
import subprocess
import shutil
import re

from pathlib import Path

from setuptools import Command

with open('eth2validatorwizard/__init__.py', 'rt') as f:
    version = re.search(r'__version__ = \'(.*?)\'', f.read()).group(1)

def get_python_binary():
    try:
        process_result = subprocess.run(['python3', '--version'])
        if process_result.returncode == 0:
            return 'python3'
    except FileNotFoundError:
        pass
    try:
        process_result = subprocess.run(['python', '--version'])
        if process_result.returncode == 0:
            return 'python'
    except FileNotFoundError:
        pass
    return None

def include_requirements(target_path):
    project_path = Path(os.getcwd())

    python_binary = get_python_binary()

    # Install packages from requirements.txt file into build dir
    requirements_path = Path(project_path, 'requirements.txt')
    subprocess.run([
        python_binary, '-m', 'pip', 'install', '-r', requirements_path,
        '--target', target_path
    ])

    # Clean __pycache__ directories
    dir_list = []
    dir_list.append(target_path)
    while len(dir_list) > 0:
        next_dir = dir_list.pop()
        with os.scandir(next_dir) as it:
            for entry in it:
                if entry.name.startswith('.'):
                    continue
                if entry.is_dir():
                    if entry.name == '__pycache__':
                        shutil.rmtree(entry.path)
                    else:
                        dir_list.append(entry.path)

    # Clean .dist-info directories
    with os.scandir(target_path) as dir_it:
        for entry in dir_it:
            if entry.name.startswith('.') or not entry.is_dir():
                continue
            
            if entry.name.endswith('.dist-info'):
                shutil.rmtree(entry.path)

def create_zipapp():
    project_path = Path(os.getcwd())
    src_package_path = Path(project_path, 'eth2validatorwizard')

    python_binary = get_python_binary()

    # Create and clean the build dir
    build_path = Path(project_path, 'build')
    if build_path.is_dir():
        shutil.rmtree(build_path)
    
    build_path.mkdir(parents=True, exist_ok=True)

    # Copy package into build dir
    build_package_path = Path(build_path, 'eth2validatorwizard')
    shutil.copytree(src_package_path, build_package_path)

    # Copy __main__.py into build root
    src_main_path = Path(src_package_path, '__main__.py')
    build_main_path = Path(build_path, '__main__.py')
    shutil.copyfile(src_main_path, build_main_path)

    include_requirements(build_path)

    # Bundle with zipapp
    dist_path = Path(project_path, 'dist')
    dist_path.mkdir(parents=True, exist_ok=True)

    bundle_name = f'eth2validatorwizard-{version}.pyz'
    bundle_path = Path(dist_path, bundle_name)
    if bundle_path.is_file():
        bundle_path.unlink()
    
    subprocess.run([
        python_binary, '-m', 'zipapp', build_path, '-p', '/usr/bin/env python3',
        '-c', '-o', bundle_path
    ])

    return bundle_path

class Bundle(Command):
    ''' Create a bundle for release
    '''
    description = 'create a bundle for release'

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        bundle_path = create_zipapp()

        project_path = Path(os.getcwd())
        dist_path = Path(project_path, 'dist')
        dist_path.mkdir(parents=True, exist_ok=True)

        bundle_name = f'eth2validatorwizard-{version}.pyz'

        # Sign bundle with GPG key
        bundle_sign_name = f'{bundle_name}.asc'
        bundle_sign_path = Path(dist_path, bundle_sign_name)
        if bundle_sign_path.is_file():
            bundle_sign_path.unlink()
        
        subprocess.run([
            'gpg', '--default-key', '6EEC4CD326C4BBC79F51F55AE68A0CC47982CB5F', '--sign',
            '--armor', '--output', bundle_sign_path, '--detach-sig', bundle_path
        ])

class BundleWin(Command):
    ''' Create a Windows bundle for release
    '''
    description = 'create a Windows bundle for release'

    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        # Find 7-Zip directory

        import winreg

        sevenzip_directory = None

        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\7-Zip') as key:
                sevenzip_directory = winreg.QueryValueEx(key, 'Path')
            
            if sevenzip_directory:
                sevenzip_directory = Path(sevenzip_directory[0])
        except OSError as exception:
            print(f'Unable to find 7-Zip directory. Exception: {exception}')
            return
        
        if sevenzip_directory is None:
            print('We could not find 7-Zip. Make sure to install 7-Zip from '
                'https://www.7-zip.org/')
            return

        sevenzip_binary = sevenzip_directory.joinpath('7z.exe')
        if not sevenzip_binary.is_file():
            print(f'We could not find the 7-Zip binary in {sevenzip_binary}')
            return

        project_path = Path(os.getcwd())
        src_package_path = Path(project_path, 'eth2validatorwizard')

        build_path = Path(project_path, 'build')
        if build_path.is_dir():
            shutil.rmtree(build_path)
        build_path.mkdir(parents=True, exist_ok=True)
        
        # Create SFX config file
        sfx_config_path = build_path.joinpath('config.txt')
        with open(sfx_config_path, 'w', encoding='utf8') as config_file:
            config_file.write(
f'''
;!@Install@!UTF-8!
Title="Eth2 Validator Wizard {version}"
ExecuteFile="python.exe"
ExecuteParameters="-m eth2validatorwizard"
;!@InstallEnd@!
'''         )

        download_path = build_path.joinpath('downloads')
        download_path.mkdir(parents=True, exist_ok=True)

        # Download Python embeddable package
        import httpx

        python_embed_url = 'https://www.python.org/ftp/python/3.9.4/python-3.9.4-embed-amd64.zip'
        python_embed_name = 'python-3.9.4-embed-amd64.zip'

        python_embed_archive = download_path.joinpath(python_embed_name)
        try:
            with open(python_embed_archive, 'wb') as binary_file:
                print(f'Downloading python archive {python_embed_name}...')
                with httpx.stream('GET', python_embed_url) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download python archive {python_embed_name}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading python archive. Exception: {exception}')
            return False

        archive_dir_path = build_path.joinpath('archive')
        archive_dir_path.mkdir(parents=True, exist_ok=True)

        # Extracting Python embeddable package
        from zipfile import ZipFile
        print(f'Extracting python archive {python_embed_name}...')
        with ZipFile(python_embed_archive, 'r') as zip_file:
            zip_file.extractall(archive_dir_path)
        
        # Download LZMA SDK for SFX modules for installers
        lzma_sdk_url = 'https://www.7-zip.org/a/lzma1900.7z'
        lzma_sdk_name = 'lzma1900.7z'

        lzma_sdk_archive = download_path.joinpath(lzma_sdk_name)
        try:
            with open(lzma_sdk_archive, 'wb') as binary_file:
                print(f'Downloading LZMA SDK archive {lzma_sdk_name}...')
                with httpx.stream('GET', lzma_sdk_url) as http_stream:
                    if http_stream.status_code != 200:
                        print(f'Cannot download LZMA SDK archive {lzma_sdk_name}.\n'
                            f'Unexpected status code {http_stream.status_code}')
                        return False
                    for data in http_stream.iter_bytes():
                        binary_file.write(data)
        except httpx.RequestError as exception:
            print(f'Exception while downloading LZMA SDK archive. Exception: {exception}')
            return False
        
        lzma_dir_path = build_path.joinpath('lzma')
        lzma_dir_path.mkdir(parents=True, exist_ok=True)

        # Extracting LZMA SDK
        subprocess.run([
            sevenzip_binary, 'x', lzma_sdk_archive, '-y'
        ], cwd=lzma_dir_path)
        
        sfx_module = lzma_dir_path.joinpath('bin', '7zSD.sfx')
        if not sfx_module.is_file():
            print(f'We could not find the 7-Zip SFX module in {lzma_dir_path}')
            return
        
        # Copy package into archive dir
        archive_package_path = archive_dir_path.joinpath('eth2validatorwizard')
        shutil.copytree(src_package_path, archive_package_path)

        include_requirements(archive_dir_path)

        # Create archive to be used with self extracting (SFX)
        sfx_archive_path = build_path.joinpath('sfx.7z')

        subprocess.run([
            sevenzip_binary, 'a', '-t7z', sfx_archive_path, '*'
        ], cwd=archive_dir_path)

        # Create distribution file
        dist_path = Path(project_path, 'dist')
        dist_path.mkdir(parents=True, exist_ok=True)

        dist_binary = dist_path.joinpath(f'eth2validatorwizard-{version}.exe')
        if dist_binary.is_file():
            dist_binary.unlink()
        
        from functools import partial

        chunk_size = 1024 * 64

        with open(dist_binary, 'wb') as dist_file:
            with open(sfx_module, 'rb') as sfx_file:
                for chunk in iter(partial(sfx_file.read, chunk_size), b''):
                    dist_file.write(chunk)
            with open(sfx_config_path, 'rb') as config_file:
                for chunk in iter(partial(config_file.read, chunk_size), b''):
                    dist_file.write(chunk)
            with open(sfx_archive_path, 'rb') as archive_file:
                for chunk in iter(partial(archive_file.read, chunk_size), b''):
                    dist_file.write(chunk)

   
if __name__ == "__main__":
    setuptools.setup(
        version=version,
        cmdclass={
            'bundle': Bundle,
            'bundlewin': BundleWin
        }
    )