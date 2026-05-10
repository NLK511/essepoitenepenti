from __future__ import annotations

from typing import Any

from trade_proposer_app.services.recommendation_plan_calibration import RecommendationPlanCalibrationService


class WatchlistCalibrationReviewService:
    """Build calibration review payloads used by watchlist plan framing."""

    def __init__(self, orchestration: Any) -> None:
        self._orchestration = orchestration

    def calibration_review(
        self,
        calibration_summary: object | None,
        setup_family: str,
        confidence_percent: float,
        *,
        horizon: str,
        transmission_summary: dict[str, object] | None = None,
    ) -> dict[str, object]:
        o = self._orchestration
        if calibration_summary is None:
            threshold_offset = o._signal_gating_tuning_value("threshold_offset", 0.0)
            confidence_adjustment = o._signal_gating_tuning_value("confidence_adjustment", 0.0)
            return {
                "enabled": False,
                "review_status": "disabled",
                "review_status_label": o._calibration_review_status_label("disabled"),
                "raw_confidence_percent": round(confidence_percent, 2),
                "calibrated_confidence_percent": round(confidence_percent + confidence_adjustment, 2),
                "confidence_adjustment": round(confidence_adjustment, 2),
                "base_confidence_threshold": round(o.confidence_threshold, 2),
                "effective_confidence_threshold": round(o.confidence_threshold + threshold_offset, 2),
                "threshold_adjustment": round(threshold_offset, 2),
                "reasons": [],
                "reason_details": [],
            }
        bucket_key = self.confidence_bucket(confidence_percent)
        base_threshold = float(o.confidence_threshold)
        overall_win_rate = self.safe_rate(getattr(calibration_summary, "overall_win_rate_percent", None))
        transmission_bias = o.taxonomy_service.derive_transmission_bias(transmission_summary)
        context_regime = o.taxonomy_service.derive_transmission_context_regime(transmission_summary)
        horizon_setup_key = f"{horizon}__{setup_family}"

        setup_bucket = self.find_calibration_bucket(getattr(calibration_summary, "by_setup_family", []), setup_family)
        confidence_bucket = self.find_calibration_bucket(getattr(calibration_summary, "by_confidence_bucket", []), bucket_key)
        horizon_bucket = self.find_calibration_bucket(getattr(calibration_summary, "by_horizon", []), horizon)
        transmission_bucket = self.find_calibration_bucket(getattr(calibration_summary, "by_transmission_bias", []), transmission_bias)
        context_regime_bucket = self.find_calibration_bucket(getattr(calibration_summary, "by_context_regime", []), context_regime)
        horizon_setup_bucket = self.find_calibration_bucket(getattr(calibration_summary, "by_horizon_setup_family", []), horizon_setup_key)

        threshold_adjustment = 0.0
        confidence_adjustment = 0.0
        reasons: list[str] = []
        calibration_curve = self.calibration_curve_snapshot(calibration_summary, confidence_percent)
        if calibration_curve is not None:
            confidence_adjustment += float(calibration_curve.get("confidence_adjustment", 0.0) or 0.0)
            if calibration_curve.get("confidence_adjustment") not in (None, 0, 0.0):
                reasons.append("calibration_curve_adjusted")
        reviewed_buckets = (
            ("setup_family", setup_bucket, 10.0, 5.0, -2.0, 1.6, 0.9, -0.6),
            ("confidence_bucket", confidence_bucket, 10.0, 5.0, -2.0, 1.2, 0.75, -0.5),
            ("horizon", horizon_bucket, 4.0, 2.0, -1.0, 0.85, 0.5, -0.3),
            ("transmission_bias", transmission_bucket, 3.0, 1.5, -0.75, 0.6, 0.35, -0.2),
            ("context_regime", context_regime_bucket, 3.0, 1.5, -0.75, 0.6, 0.35, -0.2),
            ("horizon_setup_family", horizon_setup_bucket, 4.0, 2.0, -1.0, 0.75, 0.4, -0.2),
        )
        usable_bucket_count = 0
        strong_bucket_count = 0
        for label, bucket, hard_penalty, soft_penalty, reward, hard_conf_penalty, soft_conf_penalty, conf_reward in reviewed_buckets:
            adjustment, bucket_reasons, sample_status = self.bucket_threshold_adjustment(
                label,
                bucket,
                overall_win_rate=overall_win_rate,
                hard_penalty=hard_penalty,
                soft_penalty=soft_penalty,
                reward=reward,
            )
            conf_adjustment = self.bucket_confidence_adjustment(
                label,
                bucket,
                overall_win_rate=overall_win_rate,
                hard_penalty=hard_conf_penalty,
                soft_penalty=soft_conf_penalty,
                reward=conf_reward,
            )
            if sample_status in {"usable", "strong"}:
                usable_bucket_count += 1
            if sample_status == "strong":
                strong_bucket_count += 1
            threshold_adjustment += adjustment
            confidence_adjustment += conf_adjustment
            reasons.extend(bucket_reasons)
        threshold_adjustment += o._signal_gating_tuning_value("threshold_offset", 0.0)
        confidence_adjustment += o._signal_gating_tuning_value("confidence_adjustment", 0.0)
        review_scale = 1.0
        if strong_bucket_count >= 3 and usable_bucket_count >= 5:
            review_scale = 1.0
        elif strong_bucket_count >= 2 or usable_bucket_count >= 4:
            review_scale = 0.8
        elif usable_bucket_count >= 2:
            review_scale = 0.6
        else:
            review_scale = 0.4
        threshold_adjustment *= review_scale
        confidence_adjustment *= review_scale
        threshold_adjustment = max(-6.0, min(15.0, threshold_adjustment))
        confidence_adjustment = max(-4.0, min(2.5, confidence_adjustment))
        effective_threshold = max(45.0, min(90.0, base_threshold + threshold_adjustment))
        calibrated_confidence = max(5.0, min(95.0, confidence_percent + confidence_adjustment))
        review_status = self.calibration_review_status(usable_bucket_count, strong_bucket_count)
        return {
            "enabled": True,
            "review_status": review_status,
            "raw_confidence_percent": round(confidence_percent, 2),
            "calibration_curve": calibration_curve,
            "calibrated_confidence_percent": round(calibrated_confidence, 2),
            "confidence_adjustment": round(confidence_adjustment, 2),
            "base_confidence_threshold": round(base_threshold, 2),
            "effective_confidence_threshold": round(effective_threshold, 2),
            "threshold_adjustment": round(threshold_adjustment, 2),
            "overall_win_rate_percent": overall_win_rate,
            "review_scale": round(review_scale, 2),
            "setup_family": self.bucket_snapshot(setup_family, setup_bucket),
            "confidence_bucket": self.bucket_snapshot(bucket_key, confidence_bucket),
            "horizon": self.bucket_snapshot(horizon, horizon_bucket),
            "transmission_bias": self.bucket_snapshot(transmission_bias, transmission_bucket),
            "context_regime": self.bucket_snapshot(context_regime, context_regime_bucket),
            "horizon_setup_family": self.bucket_snapshot(horizon_setup_key, horizon_setup_bucket),
            "reasons": list(dict.fromkeys(reasons)),
            "reason_details": o._calibration_reason_details(reasons),
            "review_status_label": o._calibration_review_status_label(review_status),
        }

    @staticmethod
    def find_calibration_bucket(buckets: object, key: str) -> object | None:
        if not isinstance(buckets, list):
            return None
        for bucket in buckets:
            if getattr(bucket, "key", None) == key:
                return bucket
        return None

    def bucket_threshold_adjustment(
        self,
        label: str,
        bucket: object | None,
        *,
        overall_win_rate: float | None,
        hard_penalty: float,
        soft_penalty: float,
        reward: float,
    ) -> tuple[float, list[str], str]:
        if bucket is None:
            return 0.0, [], "insufficient"
        win_rate = self.safe_rate(getattr(bucket, "win_rate_percent", None))
        sample_status = str(getattr(bucket, "sample_status", "insufficient") or "insufficient")
        if win_rate is None or overall_win_rate is None:
            return 0.0, [f"{label}_insufficient_data"], sample_status
        if sample_status in {"insufficient", "limited"}:
            return 0.0, [f"{label}_insufficient_data"], sample_status
        penalty_multiplier = 1.0 if sample_status == "strong" else 0.75
        reward_multiplier = 1.0 if sample_status == "strong" else 0.5
        if win_rate <= max(35.0, overall_win_rate - 15.0):
            return round(hard_penalty * penalty_multiplier, 2), [f"{label}_underperforming"], sample_status
        if win_rate <= max(45.0, overall_win_rate - 8.0):
            return round(soft_penalty * penalty_multiplier, 2), [f"{label}_soft_underperformance"], sample_status
        if win_rate >= min(80.0, overall_win_rate + 12.0):
            return round(reward * reward_multiplier, 2), [f"{label}_outperforming"], sample_status
        return 0.0, [], sample_status

    def bucket_confidence_adjustment(
        self,
        label: str,
        bucket: object | None,
        *,
        overall_win_rate: float | None,
        hard_penalty: float,
        soft_penalty: float,
        reward: float,
    ) -> float:
        if bucket is None:
            return 0.0
        win_rate = self.safe_rate(getattr(bucket, "win_rate_percent", None))
        sample_status = str(getattr(bucket, "sample_status", "insufficient") or "insufficient")
        if win_rate is None or overall_win_rate is None or sample_status in {"insufficient", "limited"}:
            return 0.0
        sample_multiplier = 1.0 if sample_status == "strong" else 0.65
        if win_rate <= max(35.0, overall_win_rate - 15.0):
            return round(-hard_penalty * sample_multiplier, 2)
        if win_rate <= max(45.0, overall_win_rate - 8.0):
            return round(-soft_penalty * sample_multiplier, 2)
        if win_rate >= min(80.0, overall_win_rate + 12.0):
            return round(abs(reward) * sample_multiplier, 2)
        return 0.0

    def bucket_snapshot(self, key: str, bucket: object | None) -> dict[str, object]:
        return {
            "key": key,
            "label": str(getattr(bucket, "label", key.replace("_", " ")) or key.replace("_", " ")) if bucket is not None else key.replace("_", " "),
            "slice_name": str(getattr(bucket, "slice_name", "") or "") if bucket is not None else "",
            "slice_label": str(getattr(bucket, "slice_label", "") or "") if bucket is not None else "",
            "resolved_count": int(getattr(bucket, "resolved_count", 0) or 0) if bucket is not None else 0,
            "win_rate_percent": self.safe_rate(getattr(bucket, "win_rate_percent", None)) if bucket is not None else None,
            "sample_status": str(getattr(bucket, "sample_status", "insufficient") or "insufficient") if bucket is not None else "insufficient",
            "min_required_resolved_count": int(getattr(bucket, "min_required_resolved_count", 0) or 0) if bucket is not None else 0,
            "average_return_5d": round(float(getattr(bucket, "average_return_5d", 0.0) or 0.0), 3) if bucket is not None and getattr(bucket, "average_return_5d", None) is not None else None,
        }

    def calibration_curve_snapshot(self, calibration_summary: object | None, confidence_percent: float) -> dict[str, object] | None:
        if calibration_summary is None:
            return None
        report_candidates = [
            ("recent_smoothed", getattr(calibration_summary, "recent_smoothed_calibration_report", None)),
            ("recent", getattr(calibration_summary, "recent_calibration_report", None)),
            ("smoothed", getattr(calibration_summary, "smoothed_calibration_report", None)),
            ("raw", getattr(calibration_summary, "calibration_report", None)),
        ]
        for report_scope, report in report_candidates:
            bins = getattr(report, "bins", None)
            if report is None or not isinstance(bins, list) or not bins:
                continue
            for bin_item in bins:
                bounds = self.confidence_bin_bounds(str(getattr(bin_item, "bin_key", "") or ""))
                if bounds is None:
                    continue
                lower, upper = bounds
                if not self.confidence_in_bin(confidence_percent, lower, upper):
                    continue
                try:
                    predicted_probability = float(getattr(bin_item, "predicted_probability", None))
                except (TypeError, ValueError):
                    predicted_probability = None
                realized_win_rate_percent = self.safe_rate(getattr(bin_item, "realized_win_rate_percent", None))
                resolved_count = int(getattr(bin_item, "resolved_count", 0) or 0)
                if predicted_probability is None or resolved_count < RecommendationPlanCalibrationService.RECENT_WINDOW_MIN_RESOLVED_FOR_CURVE:
                    continue
                target_confidence = round(predicted_probability * 100.0, 2) if predicted_probability <= 1.0 else round(predicted_probability, 2)
                raw_adjustment = target_confidence - confidence_percent
                cap = 6.0 if resolved_count >= 40 else 4.0 if resolved_count >= 20 else 2.0
                adjustment = round(max(-cap, min(cap, raw_adjustment)), 2)
                if adjustment == 0.0:
                    return None
                return {
                    "report_version": str(getattr(report, "version_label", "") or ""),
                    "report_scope": report_scope,
                    "bin_key": str(getattr(bin_item, "bin_key", "") or ""),
                    "bin_label": str(getattr(bin_item, "bin_label", "") or ""),
                    "resolved_count": resolved_count,
                    "predicted_probability_percent": round(target_confidence, 2),
                    "realized_win_rate_percent": realized_win_rate_percent,
                    "raw_confidence_percent": round(confidence_percent, 2),
                    "confidence_adjustment": adjustment,
                }
        return None

    @staticmethod
    def confidence_bin_bounds(bin_key: str) -> tuple[int, int] | None:
        parts = bin_key.split("_", 1)
        if len(parts) != 2:
            return None
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return None

    @staticmethod
    def confidence_in_bin(confidence: float, lower: int, upper: int) -> bool:
        if upper >= 100:
            return lower <= confidence <= upper
        return lower <= confidence < upper

    @staticmethod
    def calibration_review_status(usable_bucket_count: int, strong_bucket_count: int) -> str:
        if usable_bucket_count == 0:
            return "insufficient_data"
        if strong_bucket_count >= 2 and usable_bucket_count >= 4:
            return "strong_for_gating"
        if usable_bucket_count >= 3:
            return "usable_for_gating"
        return "heuristic_limited"

    @staticmethod
    def safe_rate(value: object) -> float | None:
        if value is None:
            return None
        try:
            return round(float(value), 1)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def confidence_bucket(confidence_percent: float) -> str:
        if confidence_percent >= 80.0:
            return "80_plus"
        if confidence_percent >= 65.0:
            return "65_to_79"
        if confidence_percent >= 50.0:
            return "50_to_64"
        return "below_50"
