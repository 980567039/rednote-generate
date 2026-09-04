import axios from 'axios'
import { API_BASE_URL } from './client'
import type { ContentResponse, SeriesRequestContext } from './types'

export async function generateContent(
  topic: string,
  outline: string,
  series?: SeriesRequestContext
): Promise<ContentResponse> {
  const response = await axios.post<ContentResponse>(`${API_BASE_URL}/content`, {
    topic,
    outline,
    ...(series || {})
  })
  return response.data
}
