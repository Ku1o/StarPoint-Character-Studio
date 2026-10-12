"""One additive handoff alongside the existing author brief, not another checklist."""
from production_brief import export_handoff


def report(store, project):
    from source_intake import source_intake_payload
    from action_presets import action_contract_payload
    from character_audit import report as character_report
    from audio_review import project_report
    from degree_editor import report as degree_report
    from entry_layout import report as entry_report
    from atlas_optimizer import validate_options
    from character_dependencies import analyze_project
    result = export_handoff(project)
    result.update(sourceIntake=source_intake_payload(project), actionContracts=action_contract_payload(project),
                  characterAudit=character_report(project), audioReview=project_report(store, project),
                  entryLayout=entry_report(project), degrees=degree_report(store, project))
    result['atlasOptimization'] = {'options': validate_options(project.get('atlasOptimization')),
                                   'status': 'compile_to_measure', 'sourceArtworkModified': False, 'gameReady': False}
    result['dependencyClosure'] = analyze_project(store, project)
    from author_gameplay import handoff as gameplay_handoff
    result['authorGameplayIntegration'] = gameplay_handoff(project, store=store)
    from author_gameplay import preview as gameplay_preview
    from dependency_assistance import build as assistance_report
    preview = gameplay_preview(project, store=store)
    result['mechanicsIntegration'] = preview['integrationPlans']
    result['assistance'] = assistance_report(project, result['dependencyClosure'], preview)
    result['uncovered'] = ['原生动作初始化/恢复 selector', '完整依赖收集与原生图集装箱',
                           '技能坐标、精确伤害、耐性和再次施放', '声音原生路径登记、自动触发和全文听感',
                           '首次 NewEntry 原生排版', '铭牌资格、事务、佩戴和存档接入']
    result['gameReady'] = False
    return result
