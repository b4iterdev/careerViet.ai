import json

from typer.testing import CliRunner

from careerviet.cli import app


def test_packaged_tracking_skill():
    result = CliRunner().invoke(app, ['applications', 'skill'])
    assert result.exit_code == 0, result.output
    assert '--confirm' in result.stdout and 'untrusted' in result.stdout


def test_tracking_cli(tmp_path):
    runner = CliRunner()
    args = ['--workspace', str(tmp_path)]
    result = runner.invoke(app, [*args, 'import-jd', '--stdin'], input='Title: Synthetic M5 job')
    assert result.exit_code == 0
    job_id = result.stdout.split()[1]
    result = runner.invoke(app, [*args, 'track', job_id])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)['state'] == 'discovered'
    assert runner.invoke(app, [*args, 'track', job_id, '--state', 'shortlisted']).exit_code == 0
    result = runner.invoke(app, [*args, 'applications', 'list', '--state', 'shortlisted'])
    assert json.loads(result.stdout)[0]['job_id'] == job_id
    assert runner.invoke(app, [*args, 'apply', job_id, '--cv', 'missing']).exit_code != 0
    assert runner.invoke(app, [*args, 'track', job_id, '--state', 'applied']).exit_code != 0
    assert runner.invoke(app, [*args, 'track', job_id, '--state', 'bogus']).exit_code != 0
    result = runner.invoke(app, [*args, 'applications', 'history', job_id])
    assert len(json.loads(result.stdout)) == 1
