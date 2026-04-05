/**
 * Document upload API client.
 *
 * Endpoints:
 *   POST   /api/datasets/{courseId}/documents/upload  — Upload a document
 *   GET    /api/datasets/{courseId}/documents          — List documents (auth-aware)
 *   DELETE /api/datasets/{courseId}/documents/{docId}  — Soft-delete a document
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost';

export type UploadedDocument = {
  id: string;
  title: string;
  status: 'processing' | 'ready' | 'error';
  chunk_count: number;
  uploaded_by: string;
  visibility: 'global' | 'private';
  deleted_at: string | null;
};

export async function uploadDocument(
  courseId: string,
  file: File
): Promise<UploadedDocument> {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API_BASE}/api/datasets/${courseId}/documents/upload`, {
    method: 'POST',
    credentials: 'include',
    body: formData,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Upload failed (${res.status}): ${text}`);
  }
  return res.json();
}

export async function listDocuments(courseId: string): Promise<{ data: UploadedDocument[] }> {
  const res = await fetch(`${API_BASE}/api/datasets/${courseId}/documents`, {
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`Failed to list documents: ${res.status}`);
  return res.json();
}

export async function deleteDocument(courseId: string, docId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/datasets/${courseId}/documents/${docId}`, {
    method: 'DELETE',
    credentials: 'include',
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Delete failed (${res.status}): ${text}`);
  }
}
