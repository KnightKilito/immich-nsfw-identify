"""Create a public-source ZIP from a whitelist; never include local credentials."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'immich-nsfw-identify'
FILES = (
    'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'compose.yaml',
    'Dockerfile', 'requirements.txt', '.env.example', '.gitignore', '.dockerignore',
    'scripts/package_source.py',
    'scripts/create_favicon.py',
)
DIRECTORIES = ('src', 'static', 'tests')


def package():
    paths = [ROOT / name for name in FILES]
    for directory in DIRECTORIES:
        paths.extend(path for path in (ROOT / directory).rglob('*')
                     if path.is_file() and '__pycache__' not in path.parts
                     and path.suffix != '.pyc')
    for path in paths:
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise RuntimeError(f'Invalid source file: {path.relative_to(ROOT)}')
    destination = ROOT / 'dist' / f'{PROJECT}-source.zip'
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, f'{PROJECT}/{path.relative_to(ROOT).as_posix()}')
    print(f'Created {destination} ({len(paths)} source files)')


if __name__ == '__main__':
    package()
