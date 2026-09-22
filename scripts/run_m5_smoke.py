"""Synthetic M5 separate-process CLI smoke; workspace cleaned on exit."""
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from careerviet.cv import CVService
from careerviet.models.profile import CandidateEvidence, CandidateProfile
from careerviet.storage.repository import CareerRepository


def main():
    with tempfile.TemporaryDirectory(prefix='careerviet-m5-smoke-') as tmp:
        workspace = Path(tmp)
        repo = CareerRepository(workspace)
        repo.save_confirmed_profile(CandidateProfile(
            profile_id='synthetic', version='v1', confirmed_at=datetime.now(UTC),
            evidence=[CandidateEvidence(evidence_id='e1', status='candidate_confirmed',
                       summary='Supported synthetic customers.', source='synthetic')]))

        def cli(*args, input=None, success=True):
            proc = subprocess.run([str(Path(sys.executable).with_name('careerviet')),
                                   '--workspace', str(workspace), *args],
                                  input=input, capture_output=True, text=True, timeout=20, check=False)
            assert (proc.returncode == 0) == success, proc.stdout + proc.stderr
            return proc.stdout

        job_id = cli('import-jd', '--stdin', input='Title: Synthetic tracking demo').split()[1]
        cvs = CVService(repo)
        cv = cvs.create('v1', ['e1'], language='en', job_id=job_id)
        cli('cv', 'approve', cv.id, '--hash', cvs.content_hash(cv))
        assert json.loads(cli('track', job_id))['state'] == 'discovered'
        for state in ('shortlisted', 'drafting'):
            cli('track', job_id, '--state', state)
        cli('track', job_id, '--state', 'ready', '--cv', cv.id)
        cli('apply', job_id, '--cv', cv.id, success=False)
        assert not repo.get_job(job_id).applied
        applied = json.loads(cli('apply', job_id, '--cv', cv.id, '--confirm'))
        assert applied['applied_at'] and repo.get_job(job_id).applied
        cli('cv', 'export', cv.id, '--output', str(workspace / 'approved-cv'))
        assert (workspace / 'approved-cv/cv.pdf').stat().st_size > 0
        cli('track', job_id, '--state', 'interviewing')
        cli('track', job_id, '--state', 'offer')
        assert json.loads(cli('applications', 'list', '--state', 'offer'))[0]['job_id'] == job_id
        history = json.loads(cli('applications', 'history', job_id))
        assert [event['to_state'] for event in history] == [
            'shortlisted', 'drafting', 'ready', 'applied', 'interviewing', 'offer']
        assert json.loads(cli('track', job_id))['submission_hash'] == applied['submission_hash']
        print('M5_SMOKE_OK: confirmation gate, PDF after apply, six transitions, immutable snapshot')


if __name__ == '__main__':
    main()
