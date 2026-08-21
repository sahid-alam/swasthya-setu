import { api } from "./api";

/* Beds, referrals and Golden Hour ranking — PRD §M5 and §M8. */

export type BedState = "FREE" | "OCCUPIED" | "RESERVED" | "CLEANING" | "OOO";

export type Ward = {
  hospital_id: string;
  hospital: string;
  ward: string;
  kind: string;
  free: number;
  occupied: number;
  reserved: number;
  cleaning: number;
  ooo: number;
  total: number;
};

export type ReferralStatus =
  "REQUESTED" | "RESERVED" | "CONFIRMED" | "ARRIVED" | "EXPIRED" | "CANCELLED";

export type Referral = {
  id: string;
  from_hospital: string;
  to_hospital: string;
  patient_name: string;
  specialty: string;
  urgency: "ROUTINE" | "URGENT" | "EMERGENCY";
  status: ReferralStatus;
  bed: string | null;
  expires_at: string | null;
  notes: string | null;
};

export type Ranked = {
  rank: number;
  hospital_id: string;
  hospital: string;
  lat: number;
  lng: number;
  drive_minutes: number;
  km: number;
  capability: number;
  viable: boolean;
  free_beds: number;
  blood_units: number;
  why: string[];
  route_is_estimated: boolean;
};

export type Ranking = {
  emergency_id: string;
  lat: number;
  lng: number;
  specialty_needed: string | null;
  duration_ms: number;
  ranked: Ranked[];
};

export const fetchOccupancy = () => api<Ward[]>("/beds/occupancy");
export const fetchReferrals = () => api<Referral[]>("/referrals?limit=50");

export const confirmReferral = (id: string) =>
  api<Referral>(`/referrals/${id}/confirm`, { method: "POST" });
export const cancelReferral = (id: string) =>
  api<Referral>(`/referrals/${id}/cancel`, { method: "POST" });

export const rankEmergency = (body: {
  lat: number;
  lng: number;
  specialty?: string;
  blood_group?: string;
  description?: string;
}) =>
  api<Ranking>("/emergency/rank", {
    method: "POST",
    body: JSON.stringify(body),
  });

/** How long a hold has left, in the words a person would use. Null once it is gone. */
export function timeLeft(expiresAt: string | null): string | null {
  if (!expiresAt) return null;
  const ms = new Date(expiresAt).getTime() - Date.now();
  if (ms <= 0) return null;
  const minutes = Math.round(ms / 60_000);
  if (minutes < 60) return `${minutes} min left`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m left`;
}
