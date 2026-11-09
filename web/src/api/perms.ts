/** 角色 × 工具权限矩阵。契约见 docs/03-api-contract.md §5。 */

import { getJson } from './client';

export interface PermMatrixTool {
  name: string;
  description: string;
  is_write: boolean;
  enabled: boolean;
  code_enabled: boolean;
  default_roles: string[];
  default_enabled: boolean;
  roles: string[];
  overridden: boolean;
}

export interface PermMatrix {
  roles: string[];
  tools: PermMatrixTool[];
}

export interface PermMatrixToolInput {
  name: string;
  enabled: boolean;
  roles: string[];
}

export function getPermMatrix(): Promise<PermMatrix> {
  return getJson<PermMatrix>('/admin/perm-matrix');
}

export function updatePermMatrix(tools: PermMatrixToolInput[]): Promise<PermMatrix> {
  return getJson<PermMatrix>('/admin/perm-matrix', {
    method: 'PUT',
    body: JSON.stringify({ tools }),
  });
}
