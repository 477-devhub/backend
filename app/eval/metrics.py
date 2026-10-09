from statistics import mean
from math import ceil
from app.services.policy import decide
from app.schemas.model import ModelAssessment
CLASSES=("normal","collapse","conflict","intrusion","loitering","uncertain")
AXES=("severity","imminence","exposure","persistence")
def ratio(n,d):return n/d if d else None

def timing_summary(values, total):
    values=sorted(values)
    return {"mean":mean(values) if values else None,
        "p50":values[ceil(len(values)*.50)-1] if values else None,
        "p95":values[ceil(len(values)*.95)-1] if values else None,
        "p99":values[ceil(len(values)*.99)-1] if values else None,
        "measured_count":len(values),"coverage":len(values)/total}

def summarize(records):
    if not records:raise ValueError("empty evaluation")
    pairs=[(r["ground_truth"],ModelAssessment.model_validate(r["prediction"])) for r in records]
    # Present ground-truth classes only; explicitly reported, failures still in denominators.
    classes=[c for c in CLASSES if any(g["event_type"]==c for g,_ in pairs)]
    f1=[];class_metrics={}
    for c in classes:
        tp=sum(g["event_type"]==c and a.event_type==c for g,a in pairs)
        fp=sum(g["event_type"]!=c and a.event_type==c for g,a in pairs)
        fn=sum(g["event_type"]==c and a.event_type!=c for g,a in pairs)
        f1.append(2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)
        class_metrics[c]={"support":tp+fn,"true_positive":tp,"false_positive":fp,
                          "false_negative":fn,"recall":ratio(tp,tp+fn),"f1":f1[-1]}
    critical=[(g,a) for g,a in pairs if g.get("critical") is True]
    critical_annotation_count=sum(isinstance(g.get("critical"),bool) for g,_ in pairs)
    normal=[(g,a) for g,a in pairs if g["event_type"]=="normal"]
    review=[(g,a) for g,a in pairs if g.get("needs_human_review") is True]
    review_annotation_count=sum(isinstance(g.get("needs_human_review"),bool) for g,_ in pairs)
    costs=[a.metadata.estimated_cost_usd for _,a in pairs if a.metadata.estimated_cost_usd is not None]
    lat=[a.metadata.latency_ms for _,a in pairs if a.metadata.latency_ms is not None]
    errors=[sum(bool(a.metadata.error_code) for _,a in pairs),len(pairs)]
    axis_errors={axis:[] for axis in AXES}
    gt_axis_counts={axis:0 for axis in AXES}
    prediction_axis_counts={axis:0 for axis in AXES}
    complete_pairs=0
    for g,a in pairs:
        gt_axes=g.get("risk_axes") or {}
        predicted_axes=a.risk_axes.model_dump() if a.risk_axes is not None else {}
        matched=0
        for axis in AXES:
            gt_value=gt_axes.get(axis)
            prediction_value=predicted_axes.get(axis)
            gt_axis_counts[axis]+=gt_value is not None
            prediction_axis_counts[axis]+=prediction_value is not None
            if gt_value is not None and prediction_value is not None:
                axis_errors[axis].append(abs(gt_value-prediction_value))
                matched+=1
        complete_pairs+=matched==len(AXES)
    scalar_errors=[error for values in axis_errors.values() for error in values]
    axis_metrics={axis:{
        "mae_measured":mean(values) if values else None,
        "pair_count":len(values),"pair_coverage":len(values)/len(pairs),
        "ground_truth_count":gt_axis_counts[axis],
        "ground_truth_coverage":gt_axis_counts[axis]/len(pairs),
        "prediction_count":prediction_axis_counts[axis],
        "prediction_coverage":prediction_axis_counts[axis]/len(pairs),
    } for axis,values in axis_errors.items()}
    timing_metrics={key:timing_summary([
        r["timings"][key] for r in records
        if r.get("timings",{}).get(key) is not None],len(pairs))
        for key in ("preprocessing_ms","execution_wall_ms","adapter_cv_preprocessing_ms",
                    "adapter_cv_worker_ms","provider_ms","end_to_end_ms")}
    return {"n":len(pairs),"macro_f1":mean(f1),"macro_f1_classes":classes,
        "class_metrics":class_metrics,"normal_count":len(normal),"error_count":errors[0],
        "error_phase_counts":{phase:sum(r.get("error_phase")==phase for r in records)
                              for phase in ("preprocessing","execution")},
        "timing_metrics":timing_metrics,
        "latency_ms_execution":timing_summary(lat,len(pairs)),
        "cost_measured_count":len(costs),
        "critical_event_recall":ratio(sum(g["event_type"]==a.event_type for g,a in critical),len(critical)),
        "critical_escalation_recall":ratio(sum(decide(a).disposition!="suppressed" for _,a in critical),len(critical)),
        "critical_annotation_count":critical_annotation_count,
        "critical_annotation_coverage":critical_annotation_count/len(pairs),
        "critical_positive_count":len(critical),
        "false_alert_rate_on_normal":ratio(sum(decide(a).disposition!="suppressed" for _,a in normal),len(normal)),
        "human_review_recall":ratio(sum(decide(a).disposition=="review" for _,a in review),len(review)),
        "human_review_annotation_count":review_annotation_count,
        "human_review_annotation_coverage":review_annotation_count/len(pairs),
        "human_review_positive_count":len(review),
        "error_rate":ratio(*errors),"latency_ms_mean":mean(lat) if lat else None,
        "cost_usd_mean_measured":mean(costs) if costs else None,"cost_coverage":len(costs)/len(pairs),
        "risk_axis_mae_measured":mean(scalar_errors) if scalar_errors else None,
        "risk_axis_pair_count":complete_pairs,
        "risk_axis_pair_coverage":complete_pairs/len(pairs),
        "risk_axis_scalar_pair_count":len(scalar_errors),
        "risk_axis_scalar_coverage":len(scalar_errors)/(len(pairs)*len(AXES)),
        "risk_axis_metrics":axis_metrics,
        "mock_count":sum(a.metadata.is_mock for _,a in pairs)}
