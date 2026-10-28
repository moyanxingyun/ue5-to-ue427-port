## Summary

Describe the workflow or compatibility problem and the change made.

## Validation

- [ ] `python -m unittest discover -s scripts/tests -v`
- [ ] Tested in the stated Unreal Engine version
- [ ] Reports remain deterministic and free of private paths
- [ ] Mutating workflows retain a dry-run, report or restore path

## Compatibility

- UE5 version:
- UE 4.27 version:
- Asset/workflow stage:

## Checklist

- [ ] No proprietary or generated Unreal assets are included
- [ ] No personal `config.json`, logs or local paths are included
- [ ] `CHANGELOG.md` updated for user-visible changes
