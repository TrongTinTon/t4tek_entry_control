/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

const FINGER_NAMES = {
    0: "Út trái",
    1: "Áp út trái",
    2: "Giữa trái",
    3: "Trỏ trái",
    4: "Cái trái",
    5: "Cái phải",
    6: "Trỏ phải",
    7: "Giữa phải",
    8: "Áp út phải",
    9: "Út phải",
};

const STATUS_LABELS = {
    active: "Đã có vân tay",
    pending_review: "Chờ duyệt",
    disabled: "Đã tắt",
    deleted: "Đã xoá",
    rejected: "Đã từ chối",
    empty: "Chưa đăng ký",
};

export class FingerprintMapField extends Component {
    static template = "t4tek_entry_control.FingerprintMapField";
    static props = {
        ...standardFieldProps,
    };

    setup() {
        this.state = useState({ selectedIndex: null });
    }

    get data() {
        let value = this.props.record.data[this.props.name] || {};
        if (typeof value === "string") {
            try {
                value = JSON.parse(value || "{}");
            } catch {
                value = {};
            }
        }

        const fingers = Array.isArray(value.fingers) ? value.fingers : [];
        const byIndex = {};
        for (const finger of fingers) {
            const index = Number(finger.index);
            if (!Number.isNaN(index)) {
                byIndex[index] = finger;
            }
        }

        return {
            pin: value.pin || "",
            count: Number(value.count || 0),
            pendingCount: Number(value.pending_count || 0),
            fingers,
            byIndex,
        };
    }

    get leftFingers() {
        return [0, 1, 2, 3].map((index) => this.getFinger(index));
    }

    get rightFingers() {
        return [6, 7, 8, 9].map((index) => this.getFinger(index));
    }

    get thumbs() {
        return [4, 5].map((index) => this.getFinger(index));
    }

    get selectedFinger() {
        if (this.state.selectedIndex === null) {
            return null;
        }
        return this.getFinger(this.state.selectedIndex);
    }

    getFinger(index) {
        const raw = this.data.byIndex[index] || {};
        const status = raw.status || (raw.has_template ? "active" : "empty");
        return {
            index,
            name: raw.name || FINGER_NAMES[index] || `Finger ${index}`,
            hasTemplate: Boolean(raw.has_template || raw.template_hash),
            hasPending: Boolean(raw.has_pending || raw.pending_template_hash),
            status,
            templateVersion: raw.template_version || "",
            templateHash: raw.template_hash || "",
            pendingTemplateHash: raw.pending_template_hash || "",
            sourceDeviceCode: raw.source_device_code || "",
            lastCollectedAt: raw.last_collected_at || "",
            lastPushedAt: raw.last_pushed_at || "",
            lastDeletedAt: raw.last_deleted_at || "",
        };
    }

    selectFinger(finger) {
        this.state.selectedIndex = finger.index;
    }

    fingerClass(finger) {
        const classes = ["o_ec_finger", `o_ec_finger_${finger.index}`];
        if (finger.status === "pending_review" || finger.hasPending) {
            classes.push("is_pending");
        } else if (finger.status === "disabled") {
            classes.push("is_disabled");
        } else if (finger.status === "deleted" || finger.status === "rejected") {
            classes.push("is_failed");
        } else if (finger.hasTemplate) {
            classes.push("is_registered");
        } else {
            classes.push("is_empty");
        }
        if (this.state.selectedIndex === finger.index) {
            classes.push("is_selected");
        }
        return classes.join(" ");
    }

    fingerTooltip(finger) {
        return `${finger.name} - ${this.statusLabel(finger.status)}`;
    }

    shortHash(hash) {
        if (!hash) {
            return "";
        }
        if (hash.length <= 18) {
            return hash;
        }
        return `${hash.slice(0, 10)}...${hash.slice(-6)}`;
    }

    statusLabel(status) {
        return STATUS_LABELS[status] || status || "Chưa đăng ký";
    }
}

export const fingerprintMapField = {
    component: FingerprintMapField,
    supportedTypes: ["json", "char", "text"],
};

registry.category("fields").add("ec_fingerprint_map", fingerprintMapField);
