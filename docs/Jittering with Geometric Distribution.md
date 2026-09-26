# Chapter 5 — Jittering

The FBR method uses these equations and the observed BOLD responses from this experiment to estimate the unknown values of all $b_i$

If this experimental design was extended to include many TRs , then note that a new stimulus would be presented on every odd TR , and on every even TR the subject would rest

In this case , it is straightforward to see that except for the first and last three TRs , the predicted BOLD response on every even TR is

$$
b_2 + b_4
$$

and the predicted BOLD response on every odd TR is

$$
b_1 + b_3 + b_5
$$

In other words , the FBR method predicts that in this experiment , the observed BOLD response on virtually every odd-numbered TR would equal one value , whereas on almost all even-numbered TRs it would equal another value

If this were true , then note that we could get a good estimate of the sum $b_2 + b_4$ , but we could not separately estimate the components $b_2$ and $b_4$

Similarly , we could get a good estimate of the sum $b_1 + b_3 + b_5$ , but we could not uniquely estimate the components $b_1$ , $b_3$ , and $b_5$

Thus , our design is flawed because $b_2$ almost always appears with $b_4$ , and $b_1$ , $b_3$ , and $b_5$ almost always appear together

To avoid this identification problem , we need to vary the amount of time between events

For example , consider the following design

| TR | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | $\cdots$ |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | :---: |
| Time | 0 | 3 | 6 | 9 | 12 | 15 | 18 | 21 | $\cdots$ |
| Events | E |  | E | E |  |  | E |  |  |
| BOLD response to 1st event | $b_1$ | $b_2$ | $b_3$ | $b_4$ | $b_5$ |  |  |  |  |
| BOLD response to 2nd event |  |  | $b_1$ | $b_2$ | $b_3$ | $b_4$ | $b_5$ |  |  |
| BOLD response to 3rd event |  |  |  | $b_1$ | $b_2$ | $b_3$ | $b_4$ | $b_5$ |  |
| BOLD response to 4th event |  |  |  |  |  |  | $b_1$ | $b_2$ |  |

<html><div style="page-break-after: always;"></div></html>

In this case , the observed BOLD response at each TR will equal

| TR | BOLD |
| ---: | --- |
| 1 | $b_1$ |
| 2 | $b_2$ |
| 3 | $b_1 + b_3$ |
| 4 | $b_1 + b_2 + b_4$ |
| 5 | $b_2 + b_3 + b_5$ |
| 6 | $b_3 + b_4$ |
| 7 | $b_1 + b_4 + b_5$ |
| 8 | $b_2 + b_5$ |

**( 5.1 )**

Note that now every equation is different , so we have a much better chance of obtaining unique and accurate estimates of each $b_i$

In the fMRI literature , the process of varying the amount of time between events is called **jittering**

Jittering is a necessary design feature in any rapid , event-related design . Without jittering , it would be impossible to separate BOLD responses from successive events or to obtain unique estimates of model parameters

A variety of jittering algorithms could prove effective , but one approach , which is both effective and popular , is to determine the time between events by sampling randomly from a truncated geometric distribution

<html><div style="page-break-after: always;"></div></html>

## Geometric Distribution for Interevent Intervals

If a geometric distribution was used to determine the interevent intervals , then the probability that the delay between events would equal $n$ TRs would be given by

$$
P(\ \mathrm{Delay} = n\ )\ = p\ ( \ 1 - p\ )\!^n
$$

**( 5.2 )**

where $p$ is a parameter between $0$ and $1$

A common choice is $p = 0.5$

The geometric distribution , which is the discrete analogue of the exponential distribution , is an attractive choice for an intertrial interval because it provides the subject no information about when the next stimulus presentation will occur

For example , with a uniform distribution there would be a fixed upper limit on the delay length , so an ideal observer would know that every blank TR increases the probability that the stimulus will appear on the next TR

At the extreme , on trials when the longest possible delay occurs , the ideal observer knows with certainty that the stimulus will appear on the next TR

The geometric is the only discrete distribution ( and the exponential is the only continuous distribution ) that provides an ideal observer no opportunity to anticipate the stimulus presentation

If $M$ blank TRs have elapsed , the probability that the stimulus will appear on the next TR is $p$ , regardless of the value of $M$

For this reason , the geometric and exponential distributions are widely used to define intertrial intervals in experiments where such anticipations could bias the results , such as simple reaction time experiments ( e.g. , Luce , 1986 )

<html><div style="page-break-after: always;"></div></html>

## Truncated Geometric Distribution

One problem with the geometric distribution , though , is that it ensures that some extremely long delays are possible

This is not usually a problem in experiments run in a psychological laboratory , but in fMRI experiments long delays are expensive

A common solution is to truncate the distribution , or in other words to place an upper limit on the length of the longest possible delay

This allows an ideal observer some opportunity to anticipate the stimulus presentation , but it guarantees no long and expensive delays

Suppose the longest delay we allow is $N_{\max}$ TRs

If we use the first $N_{\max}$ terms in Equation 5.2 to calculate the probabilities of the various delays , then the sum of probabilities will be less than $1$

Therefore , we must condition Equation 5.2 by dividing by the sum of the first $N_{\max}$ terms in Equation 5.2

In other words

$$
P(\ \mathrm{Delay} = n\ )\ =
\frac
{ \ p\ ( \ 1 - p\ )\!^n \ }
{ \ \displaystyle \sum_{i = 0}^{N_{\max}} p\ ( \ 1 - p\ )\!^i \ }
$$

**( 5.3 )**

For example , setting $p = 0.5$ and disallowing any delay longer than four TRs produces the following probability distribution

| No. of TRs in Delay | $P(\ \mathrm{Delay}\ )$ |
| ---: | ---: |
| 0 | $\frac { \ 16 \ } { \ 31 \ }$ |
| 1 | $\frac { \ 8 \ } { \ 31 \ }$ |
| 2 | $\frac { \ 4 \ } { \ 31 \ }$ |
| 3 | $\frac { \ 2 \ } { \ 31 \ }$ |
| 4 | $\frac { \ 1 \ } { \ 31 \ }$ |

Note that , as required , the probabilities sum to $1$

This same sampling scheme would be used regardless of the number of event types . That is , samples from the Equation 5.3 distribution would be used to define the delays between all consecutive events , whether or not they are the same type

To sample values from this distribution , the following algorithm can be used

Draw a random sample from a uniform $\, ( \ 0 , 1 \ ) \,$ distribution

If the sampled value is in the interval $\, ( \ 0 , 0.516 \ ] \,$ , the next delay is zero TRs ( i.e. , $0.516 = 16 / 31$ )

If the value is in the interval $\, ( \ 0.516 , 0.774 \ ] \,$ , the delay is one TR

If the value is in the interval $\, ( \ 0.774 , 0.903 \ ] \,$ , then the delay is two TRs

If the value is in the interval $\, ( \ 0.903 , 0.968 \ ] \,$ , the delay is three TRs

Finally , if a value greater than $0.968$ is obtained , then the delay is four TRs

Later in this chapter , we will consider one method for evaluating the effectiveness of any particular jittering strategy

# Microlinearity versus Macrolinearity

The FBR method uses the superposition principle to predict how BOLD responses from separate events will combine at each TR

This is the same assumption that we used in Chapter 3 to predict BOLD responses to arbitrary neural activations from the HRF

Even so , it is important to note that the timescales of these two applications of the superposition principle are different

In particular , the FBR method assumes that superposition can be used to predict how BOLD responses to events that are well separated in time will combine , whereas the HRF approach assumes that superposition can be used to predict the BOLD response to individual neural activations , no matter how brief

As a result , we refer to the HRF use of superposition as **microlinearity** and the FBR use as **macrolinearity**

As discussed in Chapter 3 , Boynton et al. ( 1996 ) showed that microlinearity holds for long-duration neural events but not for shorter durations

Dale and Buckner ( 1997 ) tested macrolinearity directly

They found strong support for this version of the superposition principle across three experiments that included conditions in which consecutive stimuli were separated by as little as 2 seconds

Thus , macrolinearity should be considered a weaker assumption than microlinearity

It is logically possible that convolving the neural activation with the HRF poorly predicts the BOLD response to each stimulus event , but that the BOLD responses to separate events nevertheless add

In this case , microlinearity is violated but macrolinearity holds
