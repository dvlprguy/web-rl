# Work Trial: Create a scalable RL environment recipe that judges models ability at converting website design to code

You should create a scalable pipeline that creates RL environments. These environments should test coding agents’ ability to replicate a multi-page web design in code (ignore functionality). For your task, you should use the [Harbor framework](https://harborframework.com/) and test your task using Claude Code with Opus 4.7.

Recipe design:

You should create a pipeline that can create tasks of the following type at scale: The agent is given screenshots of a website, it uses it to replicate a design in HTML \+ CSS and we then have a good way of grading the models performance at that task.

It is your choice to think creatively about how you can setup this pipeline, etc. \- we give you a lot of freedom here to see what you come up with.

You should:

* Create a recipe that is stable  
* Make sure you can grade the models performance on a spectrum on each generated task (continuous, not discrete)  
* Do not crawl existing websites. This is not allowed. You must generate websites from scratch. (Do not worry about budget / cost if you decide to use a model provider for this)  
* Each website that gets created from your recipe should have at least 5 pages.  
* We want a good distribution of websites / types of websites  
* Functionality is outside of the scope of this trial, we’re mainly judging design. You can ignore that for grading.

**There is nothing more important than showcasing that you have research taste and can make good decisions when it comes to building these environments.** Focus on making sure that this part is done really well before moving forward (we’d rather see a very high taste trial with only part 1 finished than a rushed / okay trial with all 3 parts finished \- quality is most important)

1. What is your grading? The model will learn your grading logic, so if your grading is bad, you’re just introducing noise to the model and making it worse. Make sure higher rewards correspond to better designs using your grading logic  
2. How complex, human-like and varied are the websites that get generated using your model?  
3. What behaviors do you observe in the models / what learnings can you get from them?

# **Part 2 (Animations)**

Normal websites , can we also add animations to the website? How can you have some animations and judge the ability of the model to perfectly replicate these animations

You can pass in video recordings to the model alongside screenshots for this.

# **Part 3 (Support Multiple Frameworks)**

HTML and CSS is just one way to create websites. Can you modify your pipeline to support the following frameworks as well:

1. React JS \+ CSS  
2. React JS \+ Tailwind CSS  
3. Solid JS \+ Tailwind CSS

# **Deliverables**

Your deliverable are:

* You recipe code (automation pipeline) \- Share through a public GitHub link  
  * Make sure in here, you have documentation on how you thought through the problem and solved different aspects of it (and point to it when you share your GitHub). It’s fine if you just ask Cursor or Claude Code to write the documentation for you as you’re going through and solving these problems. We want to see how you made decisions while doing this trial  
* At least 10 final tasks created using this recipe with  
  * Choose these tasks to showcase the distribution and complexity of your tasks. We will use these 10 \+ the code for the pipeline to judge your work  
  * Alongside a visual report of the results: when running Claude Code with Opus 4.7 10 times on the task, how well does your grader do at scoring the results? Why are do higher grades pertain to better replications of the design?  
  * Explain what are the common patterns the model struggles with in your environments  
* If you’ve done part 2, make sure to include some tasks of that type in your environment  
* If you’ve done part 3, give us a benchmark on how well the model performs using different frameworks. Extra bonus, if you can understand the patterns the model struggles with for each type of environment.

# **General Advice**

1. Always finish the previous parts fully and make sure they are done well before continuing to the next parts  
2. Over-communicate. The more we see your thoughts, the better we can understand you and the more information we have to go off of when giving you an offer

