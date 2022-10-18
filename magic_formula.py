'''
This is a backtest of the Magic Formula as described by investor Joel Greenblatt
in his books The Little Book That Beats the Market (2005) and 
The Little Book That Still Beats the Market (2010).

This algorithm is designed by Group 23 for WQU MSc Financial Engineering Capstone Project:
Hannes Rohregger
Guillermo Huguet Serra 
Jarrett Oh Jia Cheng

2022/10/18
'''

# Import all the functionality needed to run algorithms
from AlgorithmImports import *

# Define a trading algorithm that is a subclass of QCAlgorithm
class MagicFormula(QCAlgorithm):
    '''
    This method is the entry point of your algorithm where you define a series of settings.
    LEAN only calls this method one time, at the start of your algorithm.
    '''
    def Initialize(self) -> None:
        self.Debug(f'--- Initializing Algorithm ----')
        # Set start and end dates
        self.SetStartDate(2016, 1, 1)
        self.SetEndDate(2022, 10, 15)
        
        # Set warmup period for data loading
        self.SetWarmUp(100)

        # Set the starting cash balance to $1m USD
        self.SetCash(1000000)

        self.SetBenchmark("QVAL")
        
        # Daily resolution is sufficient
        self.UniverseSettings.Resolution = Resolution.Daily

        # Simulation of having brokerage account with IBKR.
        # Fees are InteractiveBrokersFee
        self.SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage, AccountType.Cash)

        # Algorithm Variables
        self.lastMonth = -1
        self.purchased_securities = {}

        # Percent holding calculations
        self.NumberSecurtitiesPortfolio = 24
        self.MonthsToKeepSecurities = 12
        self.NumberSecuritiesPerMonth = int(self.NumberSecurtitiesPortfolio / self.MonthsToKeepSecurities)
        self.percent_holding = round((self.NumberSecuritiesPerMonth/self.NumberSecurtitiesPortfolio)/self.NumberSecuritiesPerMonth,3)

        # Adding universe pipeline to algorithm
        self.AddUniverse(self.CoarseFilterFunction, self.FineFundamentalFunction)

    def CoarseFilterFunction(self, coarse: List[CoarseFundamental]) -> List[Symbol]:
        '''
        This is first level filtering
        If it is a new month:
        1) Make sure that the stock has fundamental data
        2) Sort by trading dollar volume
        3) Pass the list to FineFundamentalFunction
        '''

        if self.IsWarmingUp: 
            return Universe.Unchanged
       
        self.month = self.Time.month
        if self.month == self.lastMonth:
            return Universe.Unchanged

        self.Debug(f'--------{self.Time}------------')
        self.Debug(f'Portfolio value: {self.Portfolio.TotalPortfolioValue}')
      
        self.Debug(f'Length of self.Portfolio {len(self.Portfolio)}')

        self.lastMonth = self.month
      
        filtered = [x for x in coarse if x.HasFundamentalData]
        dollar_sorted = sorted(filtered, key=lambda x: x.DollarVolume, reverse=True)

        return [x.Symbol for x in dollar_sorted]

    def FineFundamentalFunction(self, fine: List[FineFundamental]) -> List[Symbol]:
        '''
        This is second layer filtering
        Further filtering:
        1) Marketcap > $50m
        2) USA companies in NYSE and NASDAQ
        3) Exclude Financials and Utility stocks
        4) Filter by Return on Assets > 25%
        5) Sort by Earnings Yield
        6) Sort by Return on Assets
        '''
        
        # Filter out ADRs and limit to Nasdaq and NYSE
        filtered_marketcap = [x for x in fine if x.MarketCap > 50e6]

        filtered_us = [x for x in filtered_marketcap if x.CompanyReference.CountryId == "USA"
                                        and (x.CompanyReference.PrimaryExchangeID == "NYS" or x.CompanyReference.PrimaryExchangeID == "NAS")]

        # Exclude Financial or Utility stocks
        # As their accounting is different
        # https://www.quantconnect.com/datasets/morning-star-us-fundamentals/documentation
        filtered_indu = [x for x in filtered_us if (x.AssetClassification.MorningstarSectorCode != MorningstarSectorCode.Utilities)
                            and (x.AssetClassification.MorningstarSectorCode != MorningstarSectorCode.FinancialServices)]

        # REF: https://www.quantconnect.com/docs/v2/writing-algorithms/universes/equity

        # Book
        filtered_ROA = [x for x in filtered_indu if x.ValuationRatios.ForwardROA > 0.25]

        # Earnings Yield
        # The net repurchase of shares outstanding over the market capital of the company. It is a measure of shareholder return.
        sorted_EVToEBITDA = sorted(filtered_ROA, key=lambda x: x.ValuationRatios.EVToEBITDA , reverse=True)

        # Return on Capital/Assets
        # 2 Years Forward Estimated EPS / Adjusted Close Price
        sorted_ROA = sorted(sorted_EVToEBITDA, key=lambda x: x.ValuationRatios.ForwardROA, reverse=False) 

        # Remove any securities which we are already holding
        not_holding = [f.Symbol for f in sorted_ROA if f.Symbol not in self.purchased_securities]
        
        final_list = not_holding[:self.NumberSecuritiesPerMonth]

        return final_list

    def OnSecuritiesChanged(self, changes: SecurityChanges) -> None:
        '''
        This is run every month.
        Portfolio is updated:
        1) 2 stocks are purchased
        2) Stocks that have been held for 12 months are sold.
        '''
        self.Debug('-----')
        self.Debug(f'running OnSecuritiesChanged')

        self.sell_securities(self.month)
        
        for security in changes.AddedSecurities:

            self.Debug(f"{self.Time}: Buying {security.Symbol} for holding percent {self.percent_holding} Price: {security.Price}")

            self.SetHoldings(security.Symbol, self.percent_holding, False)
            self.purchased_securities[security.Symbol] = self.Time.month

    def OnOrderEvent(self, orderEvent: OrderEvent) -> None:
        ''' For analysis purposes '''

        order = self.Transactions.GetOrderById(orderEvent.OrderId)
        if orderEvent.Status == OrderStatus.Filled:
            self.Debug(f"Order Event: {self.Time}: {order.Type}: {orderEvent}")

    def sell_securities(self, month) -> None:
        '''
        Sell function. This checks which stocks have been held for 12 months and closes these.
        '''
        self.Debug('-----')
        self.Debug(f'sell_securites function. purchased_securities : {len(self.purchased_securities)}')

        # For analysis purposes:
        total_value = 0
        for kvp in self.Portfolio:
            security_holding = kvp.Value
            symbol = security_holding.Symbol.Value
            # Quantity of the security held
            quantity = security_holding.Quantity
            # Average price of the security holdings 
            price = security_holding.AveragePrice
            total_value += quantity*price
        self.Debug(f'Total value of existing holdings: {total_value}')

        to_pop = []
        for key, value in self.purchased_securities.items():
            if value == month:
                # It's been 12 months, time to sell
                self.Debug(f"removed security: {key} from portfolio")
                self.Liquidate(key)
                to_pop.append(key)
        
        for security in to_pop:
            self.purchased_securities.pop(security)      

    def OnEndOfAlgorithm(self) -> None:
        self.Debug("Algorithm done")
