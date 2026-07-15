from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_run_and_redeploy_refresh_keyword_file_before_fail_open_prpm():
    for name in ('run.sh', 'redeploy.sh'):
        text = (ROOT / name).read_text(encoding='utf-8')
        assert text.index('cp papers.json site/papers.json') < text.index('bash run_prpm.sh')


def test_redeploy_activates_the_same_python_environment_as_full_run():
    text = (ROOT / 'redeploy.sh').read_text(encoding='utf-8')
    assert text.index('source venv/bin/activate') < text.index('bash run_prpm.sh')


def test_prpm_wrapper_exports_then_trains_and_removes_stale_profile_on_failure():
    text = (ROOT / 'run_prpm.sh').read_text(encoding='utf-8')
    assert text.index('python export_action_log.py') < text.index('python train_prpm.py')
    assert 'rm -f site/profile.json' in text
    assert 'exit 0' in text


def test_legacy_deploy_includes_prpm_runtime_files():
    text = (ROOT / 'deploy.sh').read_text(encoding='utf-8')
    for name in ('export_action_log.py', 'train_prpm.py', 'run_prpm.sh'):
        assert name in text
