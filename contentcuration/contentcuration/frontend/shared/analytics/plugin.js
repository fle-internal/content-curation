/**
 * Analytics class for handling anything analytics related, exposed in Vue as $analytics
 */
class Analytics {
  /**
   * GTM uses an array-like structure called the `dataLayer`
   *
   * @param {Array} dataLayer
   */
  constructor(dataLayer) {
    this.dataLayer = dataLayer;
  }

  /**
   * Push an event into the dataLayer
   *
   * These events could be standard GA events, or custom events that trigger tags within GTM
   *
   * @param {String} event
   * @param {{:*}} data
   */
  trackEvent(event, data = {}) {
    this.dataLayer.push({
      ...data,
      event,
    });

    if (process.env.NODE_ENV !== 'production') {
      // eslint-disable-next-line no-console
      console.info(`Analytics.trackEvent("${event}", ${JSON.stringify(data)})`);
    }
  }

  /**
   * Tracks event with specific action
   *
   * @param {String} event
   * @param {String} eventAction
   * @param {{:*}} data
   */
  trackAction(event, eventAction, data = {}) {
    this.trackEvent(event, { ...data, eventAction });
  }

  /**
   * Tracks event with click action
   *
   * @param {String} event
   * @param {String} eventLabel
   * @param {{:*}} data
   */
  trackClick(event, eventLabel, data = {}) {
    this.trackAction(event, 'Click', { ...data, eventLabel });
  }
}


/**
 * @param Vue
 * @param {Object} options
 * @param {Array} options.dataLayer
 */
export default function AnalyticsPlugin(Vue, options = {}) {
  const analytics = new Analytics(options.dataLayer);

  Vue.$analytics = analytics;
  Vue.mixin({
    computed: {
      // eslint-disable-next-line kolibri/vue-no-unused-properties
      $analytics: () => analytics,
    },
  });
}