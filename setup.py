from setuptools import find_packages, setup

setup(
    name="aribot_auth",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.110.0",
        "aiosqlite>=0.20.0",
        "sqlalchemy[asyncio]>=2.0.0",
        "alembic>=1.13.0",
        "pyjwt>=2.8.0",
        "bcrypt>=4.1.0",
        "cryptography>=42.0.0",
        "pyotp>=2.9.0",
        "slowapi>=0.1.9",
        "pydantic>=2.0.0",
    ],
)
