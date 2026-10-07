from monitor.value import prune_history
from scripts.recover_price_history import merge_history


def test_rotation_above_capacity_protects_maturing_and_mature_histories():
    history = {f'known-{i}': [[100,100]] for i in range(30)}
    for day in range(101,110):
        for i in range(30): history[f'known-{i}'].append([day,100])
        history.update({f'new-{day}-{i}': [[day,200]] for i in range(100)})
        history = prune_history(history, day, limit=50)
        assert len(history) == 50
        assert all(len(history[f'known-{i}']) == day-99 for i in range(30))
    # Capacity remains bounded and stale histories no longer outrank active ones.
    history.update({f'active-{i}': [[120,50]] for i in range(50)})
    assert all(k.startswith('active-') for k in prune_history(history,120,limit=50))


def test_recovery_is_conservative_idempotent_and_does_not_invent_days():
    current = {'a': [[100,90]]}
    snapshots = [{'a': [[99,100],[100,95]], 'b': [[98,50],[101,1], [60,3], [99,float('nan')]]}]
    result = merge_history(current,snapshots,100)
    assert result == {'b': [(98,50)], 'a': [(99,100),(100,90)]}
    assert merge_history(result,snapshots,100) == result
