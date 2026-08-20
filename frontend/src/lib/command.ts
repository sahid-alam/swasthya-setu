import { api } from "./api";

export type Alert = {
  kind: string;
  severity: "critical" | "warn" | "info";
  title: string;
  detail: string;
  hospital: string;
  department: string | null;
  doctor_id: string | null;
  department_id: string | null;
};

export type Facility = {
  hospital_id: string;
  name: string;
  code: string;
  district: string;
  level: string;
  lat: number;
  lng: number;
  present: number;
  doctors: number;
  waiting: number;
  alerts: number;
  worst_severity: "critical" | "warn" | "info" | null;
};

export type Dept = {
  id: string;
  name: string;
  hospital: string;
  hospital_id: string;
  waiting: number;
};

export type QueueEntry = {
  position: number;
  appointment_id: string;
  patient_name: string;
  scheduled_for: string;
  priority: string;
  predicted_wait_minutes: number | null;
  noshow_prob: number | null;
  doctor_name: string;
};

export const fetchAlerts = () => api<Alert[]>("/alerts");
export const fetchNetwork = () => api<Facility[]>("/network");
export const fetchDepartments = () => api<Dept[]>("/departments");
export const fetchQueue = (departmentId: string) =>
  api<QueueEntry[]>(`/scheduling/queue?department_id=${departmentId}`);

/** DESIGN.md §9d: alert severity maps to chip tone, and never colour alone. */
export const SEVERITY_TONE = {
  critical: "danger",
  warn: "warn",
  info: "info",
} as const;
