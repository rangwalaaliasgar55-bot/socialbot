import express, { Application } from 'express'
import cors from 'cors'
import compression from 'compression'
import 'express-async-errors'
import { env } from './config/env'
import { errorHandler } from './middleware/errorHandler'
import { httpLogger } from './middleware/logger'
import { systemRouter } from './modules/system'
import { socialRouter } from './modules/social'
import { plannerRouter } from './modules/planner'
import { aiRouter } from './modules/ai'
// ============================================
// Add your domain module imports here
// ============================================
// Example: Product Module
// import { productRouter } from './modules/product.js'

export const createApp = (): Application => {
  const app = express()

  // HTTP request logging
  app.use(httpLogger)

  app.use(
    cors({
      origin: env.CORS_ORIGIN === '*' ? '*' : env.CORS_ORIGIN,
      credentials: env.CORS_ORIGIN !== '*',
    })
  )

  // Body parsing and compression
  app.use(express.json())
  app.use(express.urlencoded({ extended: true }))
  app.use(compression())

  // API routes - System & Health
  app.use(env.API_PREFIX, systemRouter)

  // Social analytics automation module
  app.use(env.API_PREFIX, socialRouter)

  // Content planner + scheduler + suggestions module
  app.use(env.API_PREFIX, plannerRouter)

  // AI copy + image + audience chat module
  app.use(env.API_PREFIX, aiRouter)

  // ============================================
  // Add your domain module routes here
  // ============================================
  // Example: Product Module
  // app.use(`${env.API_PREFIX}/products`, productRouter)

  // Error handling
  app.use(errorHandler)

  return app
}
