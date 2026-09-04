import axios from 'axios'
import { API_BASE_URL } from './client'
import type { OutlineResponse, SeriesRequestContext } from './types'

export async function generateOutline(
  topic: string,
  images?: File[],
  series?: SeriesRequestContext
): Promise<OutlineResponse & { has_images?: boolean }> {
  if (images && images.length > 0) {
    const formData = new FormData()
    formData.append('topic', topic)
    Object.entries(series || {}).forEach(([key, value]) => formData.append(key, String(value)))
    images.forEach((file) => {
      formData.append('images', file)
    })

    const response = await axios.post<OutlineResponse & { has_images?: boolean }>(
      `${API_BASE_URL}/outline`,
      formData,
      {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      }
    )
    return response.data
  }

  const response = await axios.post<OutlineResponse>(`${API_BASE_URL}/outline`, {
    topic,
    ...(series || {})
  })
  return response.data
}
