import { NetworkStateResponse, NetworkSolution, ProvenanceTag } from '../types';

const API_BASE = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000';

export async function fetchNetworkState(): Promise<NetworkStateResponse> {
  const res = await fetch(`${API_BASE}/api/state`);
  if (!res.ok) {
    throw new Error(`Failed to fetch state: ${res.statusText}`);
  }
  return res.json();
}

export async function runOptimization(params?: {
  region_name?: string;
  target_warehouses?: number;
  service_radius_minutes?: number;
  budget_limit_usd?: number;
}): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE}/api/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params || {})
  });
  if (!res.ok) {
    throw new Error(`Failed to trigger optimization: ${res.statusText}`);
  }
  return res.json();
}

export async function triggerDisruption(scenarioType: string): Promise<{ message: string; active_solution_id: string }> {
  const res = await fetch(`${API_BASE}/api/disrupt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scenario_type: scenarioType })
  });
  if (!res.ok) {
    throw new Error(`Failed to trigger disruption: ${res.statusText}`);
  }
  return res.json();
}

export async function switchSolution(solutionId: string): Promise<{ message: string; solution: NetworkSolution }> {
  const res = await fetch(`${API_BASE}/api/switch-solution`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ solution_id: solutionId })
  });
  if (!res.ok) {
    throw new Error(`Failed to switch solution: ${res.statusText}`);
  }
  return res.json();
}

export async function askNarrator(query: string): Promise<{
  answer: string;
  related_candidate_id?: string;
  provenance?: Record<string, ProvenanceTag>;
  frontier_count?: number;
}> {
  const res = await fetch(`${API_BASE}/api/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query })
  });
  if (!res.ok) {
    throw new Error(`Failed to query narrator: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchProvenanceHistory(): Promise<{ call_count: number; history: any[] }> {
  const res = await fetch(`${API_BASE}/api/provenance-trace`);
  if (!res.ok) {
    throw new Error(`Failed to fetch provenance history: ${res.statusText}`);
  }
  return res.json();
}
