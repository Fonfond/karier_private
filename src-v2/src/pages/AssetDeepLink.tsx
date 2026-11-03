import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

/** Глубокие ссылки из QR: /asset/{id} → карта с открытой карточкой. */
export function AssetDeepLink() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()

  useEffect(() => {
    if (id) navigate('/map', { replace: true, state: { openAssetId: id } })
    else navigate('/map', { replace: true })
  }, [id, navigate])

  return null
}
