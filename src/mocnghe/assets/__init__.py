from importlib.resources import files


def runtime_skill_readme() -> str:
    return files("mocnghe.assets.skills").joinpath("README.md").read_text(encoding="utf-8")
